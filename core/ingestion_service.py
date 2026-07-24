from __future__ import annotations

from pathlib import Path

from core.config import Settings
from core.enums import (
    MemoryOrigin,
    MemoryState,
    MemoryType,
    coerce_enum,
)
from core.models import SourceDocument
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from extraction.visual_parser import OpenAICompatibleVisionProvider, is_visual_file, load_visual_document
from extraction.markdown_parser import (
    content_hash,
    load_document,
    segment_document,
    stable_id,
)


class IngestionService:
    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository,
        vectors: VectorMemory,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.vectors = vectors

    def _initial_memory_state(
        self,
        origin: MemoryOrigin,
    ) -> MemoryState:
        """Choose lifecycle state from the server-owned memory origin.

        Direct user statements are active. Model-generated inferences are
        candidates. Semantic type and importance are supplied by the model.
        """
        return (
            MemoryState.CANDIDATE
            if origin == MemoryOrigin.MODEL_INFERENCE
            else MemoryState.ACTIVE
        )

    @staticmethod
    def _normalize_exclusions(
        root: Path,
        configured: list[str],
        requested: list[str] | None,
    ) -> tuple[set[str], set[str]]:
        names: set[str] = set()
        relative_paths: set[str] = set()

        for value in [*configured, *(requested or [])]:
            normalized = value.strip().strip("/\\")
            if not normalized:
                continue

            if "/" in normalized or "\\" in normalized:
                relative_paths.add(Path(normalized).as_posix())
            else:
                names.add(normalized)

        return names, relative_paths

    @staticmethod
    def _is_excluded(
        path: Path,
        root: Path,
        excluded_names: set[str],
        excluded_paths: set[str],
    ) -> bool:
        relative_parts = path.relative_to(root).parts

        if any(part in excluded_names for part in relative_parts[:-1]):
            return True

        parent = Path(*relative_parts[:-1]).as_posix()
        return any(
            parent == excluded or parent.startswith(f"{excluded}/")
            for excluded in excluded_paths
        )

    def discover(
        self,
        directory: Path,
        excludes: list[str] | None = None,
        *,
        include_visual: bool = True,
    ) -> list[Path]:
        root = directory.expanduser().resolve()

        if not root.exists():
            raise FileNotFoundError(f"Scan directory does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Scan target is not a directory: {root}")

        excluded_names, excluded_paths = self._normalize_exclusions(
            root,
            self.settings.exclude_dirs,
            excludes,
        )

        paths: set[Path] = set()
        patterns = list(self.settings.include_globs)
        if include_visual:
            patterns.extend(self.settings.visual_globs)
        for pattern in patterns:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                if self._is_excluded(
                    path,
                    root,
                    excluded_names,
                    excluded_paths,
                ):
                    continue
                paths.add(path)

        return sorted(paths)

    def scan(
        self,
        directory: Path,
        force: bool = False,
        excludes: list[str] | None = None,
        *,
        vision: bool = True,
        vision_model: str | None = None,
        vision_base_url: str | None = None,
    ) -> dict:
        root = directory.expanduser().resolve()
        files = self.discover(root, excludes, include_visual=vision)
        provider = self._vision_provider(vision_model, vision_base_url) if any(is_visual_file(p) for p in files) else None

        root_key = root.as_posix()
        current = {
            f"{root_key}::{path.relative_to(root).as_posix()}"
            for path in files
        }
        indexed = self.repository.file_paths_for_root(root_key)

        summary = {
            "root": str(root),
            "discovered": len(files),
            "indexed": 0,
            "unchanged": 0,
            "deleted": 0,
            "segments": 0,
            "visual_files": sum(1 for path in files if is_visual_file(path)),
            "excluded": sorted(
                set(self.settings.exclude_dirs) | set(excludes or [])
            ),
        }

        for removed in sorted(indexed - current):
            removed_ok, segment_ids = self.repository.delete_source(removed)
            if removed_ok:
                self.vectors.delete(segment_ids)
                summary["deleted"] += 1

        for path in files:
            doc = (
                load_visual_document(path, root, provider)
                if is_visual_file(path) and provider is not None
                else load_document(path, root)
            )

            stored_path = f"{root_key}::{doc.relative_path}"
            doc = SourceDocument(
                source_id=stable_id("src", stored_path),
                path=doc.path,
                relative_path=stored_path,
                title=doc.title,
                content=doc.content,
                content_hash=doc.content_hash,
                modified_ns=doc.modified_ns,
                size_bytes=doc.size_bytes,
            )

            if (
                not force
                and self.repository.source_hash(stored_path)
                == doc.content_hash
            ):
                summary["unchanged"] += 1
                continue

            segments = segment_document(
                doc,
                self.settings.chunk_size,
                self.settings.chunk_overlap,
            )
            for segment in segments:
                segment.memory_state = MemoryState.ACTIVE
                segment.memory_origin = MemoryOrigin.IMPORTED_FILE
            changes = self.repository.reconcile_document(doc, segments)
            self.vectors.upsert_document(
                doc,
                segments,
                deleted_ids=changes["deleted"],
            )

            summary["indexed"] += 1
            summary["segments"] += len(segments)

        return summary


    def ingest_text(
        self,
        *,
        source_path: str,
        title: str,
        text: str,
        source_kind: str = "file",
        force: bool = False,
    ) -> dict:
        normalized_path = source_path.strip()
        if not normalized_path:
            raise ValueError("source_path cannot be empty")
        body = text.strip()
        if not body:
            raise ValueError("text cannot be empty")

        digest = content_hash(body)
        if not force and self.repository.source_hash(normalized_path) == digest:
            return {"indexed": 0, "unchanged": 1, "segments": 0}

        doc = SourceDocument(
            source_id=stable_id("src", normalized_path),
            path=Path(normalized_path),
            relative_path=normalized_path,
            title=title.strip() or normalized_path,
            content=body,
            content_hash=digest,
            modified_ns=0,
            size_bytes=len(body.encode("utf-8")),
        )
        segments = segment_document(
            doc,
            self.settings.chunk_size,
            self.settings.chunk_overlap,
        )
        for segment in segments:
            segment.memory_state = MemoryState.ACTIVE
            segment.memory_origin = (
                MemoryOrigin.SPECIALTY
                if source_kind == "web"
                else MemoryOrigin.IMPORTED_FILE
            )
        changes = self.repository.reconcile_document(
            doc, segments, source_kind=source_kind
        )
        self.vectors.upsert_document(
            doc, segments, deleted_ids=changes["deleted"]
        )
        return {"indexed": 1, "unchanged": 0, "segments": len(segments)}

    def _vision_provider(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ) -> OpenAICompatibleVisionProvider:
        resolved_model = model or self.settings.vision_model
        if not resolved_model:
            raise RuntimeError(
                "Visual files were found, but no vision model is configured. "
                "Use --vision-model or set CM_VISION_MODEL. Use --no-vision to skip images."
            )
        return OpenAICompatibleVisionProvider(
            base_url=base_url or self.settings.vision_base_url,
            model=resolved_model,
            api_key=self.settings.vision_api_key,
            timeout=self.settings.vision_timeout,
        )

    def ingest_file(
        self,
        path: Path,
        *,
        force: bool = False,
        vision: bool = True,
        vision_model: str | None = None,
        vision_base_url: str | None = None,
    ) -> dict:
        file_path = path.expanduser().resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Scan file does not exist: {file_path}")
        if not file_path.is_file():
            raise IsADirectoryError(f"Scan target is not a file: {file_path}")
        if is_visual_file(file_path):
            if not vision:
                raise ValueError("Visual scan disabled for an image target")
            provider = self._vision_provider(vision_model, vision_base_url)
            doc = load_visual_document(file_path, file_path.parent, provider)
            source_kind = "visual"
        else:
            doc = load_document(file_path, file_path.parent)
            source_kind = "file"
        stored_path = file_path.as_posix()
        if not force and self.repository.source_hash(stored_path) == doc.content_hash:
            return {"indexed": 0, "unchanged": 1, "segments": 0}
        doc = SourceDocument(
            source_id=stable_id("src", stored_path),
            path=doc.path,
            relative_path=stored_path,
            title=doc.title,
            content=doc.content,
            content_hash=doc.content_hash,
            modified_ns=doc.modified_ns,
            size_bytes=doc.size_bytes,
        )
        segments = segment_document(
            doc, self.settings.chunk_size, self.settings.chunk_overlap
        )
        for segment in segments:
            segment.memory_state = MemoryState.ACTIVE
            segment.memory_origin = MemoryOrigin.IMPORTED_FILE
        changes = self.repository.reconcile_document(
            doc, segments, source_kind=source_kind
        )
        self.vectors.upsert_document(doc, segments, deleted_ids=changes["deleted"])
        return {"indexed": 1, "unchanged": 0, "segments": len(segments)}

    def remember(
        self,
        title: str,
        text: str,
        concepts: list[str] | None = None,
        *,
        memory_type: int | MemoryType,
        importance: float,
        memory_origin: MemoryOrigin,
    ) -> dict:
        source_id = stable_id("mem", title)
        doc = SourceDocument(
            source_id=source_id,
            path=Path(f"memory://{source_id}"),
            relative_path=f"memory://{source_id}",
            title=title,
            content=text,
            content_hash=content_hash(text),
            modified_ns=0,
            size_bytes=len(text.encode("utf-8")),
        )
        segments = segment_document(
            doc,
            self.settings.chunk_size,
            self.settings.chunk_overlap,
        )
        origin = coerce_enum(MemoryOrigin, memory_origin)
        state = self._initial_memory_state(origin)
        kind = coerce_enum(MemoryType, memory_type)
        importance_value = max(0.0, min(2.0, float(importance)))
        confidence_value = self.settings.automatic_memory_confidence
        source_quality_value = self.settings.automatic_memory_source_quality
        if not 0.0 <= importance_value <= 2.0:
            raise ValueError("importance must be between 0.0 and 2.0")
        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        if not 0.0 <= source_quality_value <= 1.0:
            raise ValueError("source_quality must be between 0.0 and 1.0")

        for segment in segments:
            segment.memory_state = state
            segment.memory_type = kind
            segment.memory_origin = origin
            segment.importance = importance_value
            segment.confidence = confidence_value
            segment.source_quality = source_quality_value

        if concepts:
            normalized = [
                concept.strip().lower()
                for concept in concepts
                if concept.strip()
            ]
            for segment in segments:
                segment.concepts = list(
                    dict.fromkeys(normalized + segment.concepts)
                )

        changes = self.repository.reconcile_document(
            doc,
            segments,
            source_kind="memory",
        )
        self.vectors.upsert_document(
            doc,
            segments,
            deleted_ids=changes["deleted"],
        )

        return {
            "source_id": source_id,
            "segments": len(segments),
            "memory_state": int(state),
            "memory_state_name": state.name,
            "memory_type": int(kind),
            "memory_type_name": kind.name,
            "memory_origin": int(origin),
            "memory_origin_name": origin.name,
            "importance": importance_value,
            "confidence": confidence_value,
            "source_quality": source_quality_value,
        }

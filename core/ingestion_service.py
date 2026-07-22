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

    @staticmethod
    def _initial_memory_policy(
        title: str,
        text: str,
        origin: MemoryOrigin,
    ) -> tuple[MemoryState, MemoryType]:
        """Choose server-owned lifecycle and type metadata.

        Direct user statements are active by default, but sensitive personal
        history is retained conservatively as a candidate until it is
        reinforced or manually promoted. Model inferences are always
        candidates and are explicitly typed as inferences.
        """
        if origin == MemoryOrigin.MODEL_INFERENCE:
            return MemoryState.CANDIDATE, MemoryType.INFERENCE

        combined = f"{title} {text}".casefold()

        sensitive_markers = (
            "sexual assault",
            "sexual abuse",
            "childhood abuse",
            "domestic abuse",
            "domestic violence",
            "rape",
            "molest",
            "trauma",
            "self-harm",
            "suicide attempt",
            "mental health diagnosis",
            "medical diagnosis",
        )
        state = (
            MemoryState.CANDIDATE
            if any(marker in combined for marker in sensitive_markers)
            else MemoryState.ACTIVE
        )

        type_markers: tuple[tuple[MemoryType, tuple[str, ...]], ...] = (
            (
                MemoryType.PREFERENCE,
                (
                    "prefer",
                    "preference",
                    "favorite",
                    "favourite",
                    "likes ",
                    "dislikes ",
                ),
            ),
            (
                MemoryType.RELATIONSHIP,
                (
                    "husband",
                    "wife",
                    "spouse",
                    "partner",
                    "mother",
                    "father",
                    "sister",
                    "brother",
                    "family",
                ),
            ),
            (
                MemoryType.PROJECT,
                (
                    "project",
                    "repository",
                    "codebase",
                    "working on",
                    "building",
                    "developing",
                ),
            ),
            (
                MemoryType.SKILL,
                (
                    "skilled",
                    "proficient",
                    "experience with",
                    "knows how to",
                    "programming language",
                ),
            ),
            (
                MemoryType.PROCEDURE,
                (
                    "workflow",
                    "procedure",
                    "process",
                    "steps to",
                    "how to",
                ),
            ),
            (
                MemoryType.OBSERVATION,
                ("noticed", "observed", "seems to", "appears to"),
            ),
        )
        for memory_type, markers in type_markers:
            if any(marker in combined for marker in markers):
                return state, memory_type

        return state, MemoryType.FACT

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
        for pattern in self.settings.include_globs:
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
    ) -> dict:
        root = directory.expanduser().resolve()
        files = self.discover(root, excludes)

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
            doc = load_document(path, root)

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

    def remember(
        self,
        title: str,
        text: str,
        concepts: list[str] | None = None,
        *,
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
        state, kind = self._initial_memory_policy(title, text, origin)
        importance_value = self.settings.automatic_memory_importance
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

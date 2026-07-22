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
        memory_state: int | MemoryState = MemoryState.ACTIVE,
        memory_type: int | MemoryType = MemoryType.UNKNOWN,
        memory_origin: int | MemoryOrigin = MemoryOrigin.EXPLICIT_USER,
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
        state = coerce_enum(MemoryState, memory_state)
        kind = coerce_enum(MemoryType, memory_type)
        origin = coerce_enum(MemoryOrigin, memory_origin)
        for segment in segments:
            segment.memory_state = state
            segment.memory_type = kind
            segment.memory_origin = origin

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
        }

from __future__ import annotations

from pathlib import Path

from core.config import Settings
from core.models import SourceDocument
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from extraction.markdown_parser import content_hash, load_document, segment_document, stable_id


class IngestionService:
    def __init__(self, settings: Settings, repository: SQLiteRepository, vectors: VectorMemory) -> None:
        self.settings = settings
        self.repository = repository
        self.vectors = vectors

    def discover(self) -> list[Path]:
        paths: set[Path] = set()
        excluded = set(self.settings.exclude_dirs)
        for pattern in self.settings.include_globs:
            for path in self.settings.prompt_dir.rglob(pattern):
                if path.is_file() and not any(part in excluded for part in path.relative_to(self.settings.prompt_dir).parts):
                    paths.add(path)
        return sorted(paths)

    def scan(self, force: bool = False) -> dict:
        files = self.discover()
        current = {path.relative_to(self.settings.prompt_dir).as_posix() for path in files}
        indexed = self.repository.file_paths()
        summary = {"discovered": len(files), "indexed": 0, "unchanged": 0, "deleted": 0, "segments": 0}
        for removed in sorted(indexed - current):
            ok, ids = self.repository.delete_source(removed)
            if ok:
                self.vectors.delete(ids)
                summary["deleted"] += 1
        for path in files:
            doc = load_document(path, self.settings.prompt_dir)
            if not force and self.repository.source_hash(doc.relative_path) == doc.content_hash:
                summary["unchanged"] += 1
                continue
            segments = segment_document(doc, self.settings.chunk_size, self.settings.chunk_overlap)
            self.repository.replace_document(doc, segments)
            self.vectors.replace_document(doc, segments)
            summary["indexed"] += 1
            summary["segments"] += len(segments)
        return summary

    def remember(self, title: str, text: str, concepts: list[str] | None = None) -> dict:
        source_id = stable_id("mem", title, content_hash(text))
        doc = SourceDocument(source_id, Path(f"memory://{source_id}"), f"memory://{source_id}", title,
                             text, content_hash(text), 0, len(text.encode("utf-8")))
        segments = segment_document(doc, self.settings.chunk_size, self.settings.chunk_overlap)
        if concepts:
            for segment in segments:
                segment.concepts = list(dict.fromkeys([c.strip().lower() for c in concepts if c.strip()] + segment.concepts))
        self.repository.replace_document(doc, segments, source_kind="memory")
        self.vectors.replace_document(doc, segments)
        return {"source_id": source_id, "segments": len(segments)}

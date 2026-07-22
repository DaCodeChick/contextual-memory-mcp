from __future__ import annotations

from functools import cached_property

from core.config import Settings
from core.context_builder import ContextBuilder
from core.ingestion_service import IngestionService
from core.retrieval_engine import RetrievalEngine
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from providers.embeddings import SentenceTransformerProvider


class ContextualMemoryMatrix:
    """Facade over persistent source, vector, graph, and retrieval layers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.settings.prepare()

        self.repository = SQLiteRepository(self.settings.sqlite_path)
        self.repository.initialize()

    @cached_property
    def embedder(self) -> SentenceTransformerProvider:
        return SentenceTransformerProvider(self.settings.embedding_model)

    @cached_property
    def vectors(self) -> VectorMemory:
        return VectorMemory(
            self.settings.chroma_path,
            self.settings.collection_name,
            self.embedder,
        )

    @cached_property
    def ingestion(self) -> IngestionService:
        return IngestionService(
            self.settings,
            self.repository,
            self.vectors,
        )

    @cached_property
    def retrieval(self) -> RetrievalEngine:
        return RetrievalEngine(
            self.settings,
            self.repository,
            self.vectors,
        )

    @cached_property
    def context(self) -> ContextBuilder:
        return ContextBuilder(self.settings, self.retrieval)

    def update_lifecycle(
        self,
        segment_id: str,
        *,
        memory_state: int | None = None,
        memory_type: int | None = None,
        memory_origin: int | None = None,
    ) -> dict:
        result = self.repository.set_segment_lifecycle(
            segment_id,
            memory_state=memory_state,
            memory_type=memory_type,
            memory_origin=memory_origin,
        )
        self.vectors.update_lifecycle(
            segment_id,
            memory_state=result["memory_state"],
            memory_type=result["memory_type"],
            memory_origin=result["memory_origin"],
        )
        return result

    def clear(self) -> dict:
        vector_count = self.vectors.count()
        sqlite_counts = self.repository.stats()

        self.vectors.clear()
        self.repository.clear()

        return {
            "cleared": True,
            "deleted": {
                **sqlite_counts,
                "vectors": vector_count,
            },
            "sqlite_path": str(self.settings.sqlite_path),
            "chroma_path": str(self.settings.chroma_path),
        }

    def stats(self) -> dict:
        result = self.repository.stats()
        result["vectors"] = self.vectors.count()
        result["sqlite_path"] = str(self.settings.sqlite_path)
        result["chroma_path"] = str(self.settings.chroma_path)
        return result


# Temporary compatibility alias for code written against the first prototype.
PromptMemoryMatrix = ContextualMemoryMatrix

from __future__ import annotations

from functools import cached_property

from core.config import Settings
from core.context_builder import ContextBuilder
from core.ingestion_service import IngestionService
from core.lifecycle import LifecyclePolicy
from core.lifecycle_service import LifecycleRunResult, LifecycleService
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

    @cached_property
    def lifecycle(self) -> LifecycleService:
        policy = LifecyclePolicy(
            promotion_importance=(
                self.settings.lifecycle_promotion_importance
            ),
            promotion_access_count=(
                self.settings.lifecycle_promotion_access_count
            ),
            minimum_confidence=(
                self.settings.lifecycle_minimum_confidence
            ),
            minimum_source_quality=(
                self.settings.lifecycle_minimum_source_quality
            ),
            archive_importance=(
                self.settings.lifecycle_archive_importance
            ),
            archive_after_days=(
                self.settings.lifecycle_archive_after_days
            ),
        )
        return LifecycleService(self.repository, policy)

    def run_lifecycle(self, *, apply: bool = True) -> LifecycleRunResult:
        result = self.lifecycle.run(apply=apply)
        if apply:
            for segment_id in result.changed_segment_ids:
                metadata = self.repository.lifecycle_metadata(segment_id)
                self.vectors.update_lifecycle(
                    segment_id,
                    memory_state=int(metadata["memory_state"]),
                    memory_type=int(metadata["memory_type"]),
                    memory_origin=int(metadata["memory_origin"]),
                )
        return result

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

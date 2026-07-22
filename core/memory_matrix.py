from __future__ import annotations

from functools import cached_property

from core.config import Settings
from core.context_builder import ContextBuilder
from core.ingestion_service import IngestionService
from core.retrieval_engine import RetrievalEngine
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from providers.embeddings import SentenceTransformerProvider


class PromptMemoryMatrix:
    """Facade over persistent source, vector, graph, retrieval, and context layers."""

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
        return VectorMemory(self.settings.chroma_path, self.settings.collection_name, self.embedder)

    @cached_property
    def ingestion(self) -> IngestionService:
        return IngestionService(self.settings, self.repository, self.vectors)

    @cached_property
    def retrieval(self) -> RetrievalEngine:
        return RetrievalEngine(self.settings, self.repository, self.vectors)

    @cached_property
    def context(self) -> ContextBuilder:
        return ContextBuilder(self.settings, self.retrieval)

    def stats(self) -> dict:
        result = self.repository.stats()
        result["vectors"] = self.vectors.count()
        result["sqlite_path"] = str(self.settings.sqlite_path)
        result["chroma_path"] = str(self.settings.chroma_path)
        return result

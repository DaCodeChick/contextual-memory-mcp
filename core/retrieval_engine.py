from __future__ import annotations

from core.config import Settings
from core.enums import MemoryOrigin, MemoryState, MemoryType
from core.models import SearchHit
from core.ranking import rank_memory
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from extraction.markdown_parser import extract_concepts


class RetrievalEngine:
    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository,
        vectors: VectorMemory,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.vectors = vectors

    def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        record_access: bool = True,
    ) -> list[SearchHit]:
        query = query.strip()
        if not query:
            return []

        requested = top_k or self.settings.default_top_k
        requested = max(1, min(requested, 50))

        vector_hits = self.vectors.search(
            query,
            max(40, requested * 5),
            memory_state=int(MemoryState.ACTIVE),
        )
        ids = [hit["segment_id"] for hit in vector_hits]
        metadata = self.repository.source_metadata(ids, active_only=True)
        concepts = self.repository.concepts_for(ids)
        lexical = self.repository.lexical_scores(query)
        graph = self.repository.graph_scores(extract_concepts(query, limit=10))

        hits: list[SearchHit] = []
        for item in vector_hits:
            segment_id = item["segment_id"]
            row = metadata.get(segment_id)
            if not row:
                continue

            vector_score = float(item["vector_score"])
            lexical_score = lexical.get(segment_id, 0.0)
            graph_score = graph.get(segment_id, 0.0)
            importance = float(row["importance"])
            confidence = float(row["confidence"])
            source_quality = float(row["source_quality"])
            access_count = int(row["access_count"])
            pinned = bool(row["pinned"])
            memory_state = MemoryState(int(row["memory_state"]))
            memory_type = MemoryType(int(row["memory_type"]))
            memory_origin = MemoryOrigin(int(row["memory_origin"]))
            ranking = rank_memory(
                vector_score=vector_score,
                lexical_score=lexical_score,
                graph_score=graph_score,
                importance=importance,
                confidence=confidence,
                source_quality=source_quality,
                access_count=access_count,
                pinned=pinned,
                last_accessed_at=row["last_accessed_at"],
                indexed_at=row["indexed_at"],
                recency_half_life_days=(
                    self.settings.ranking_recency_half_life_days
                ),
            )

            hits.append(
                SearchHit(
                    segment_id=segment_id,
                    source_id=row["source_id"],
                    source_path=row["source_path"],
                    title=row["title"],
                    heading=row["heading"],
                    text=row["text"],
                    score=ranking.score,
                    vector_score=vector_score,
                    lexical_score=lexical_score,
                    graph_score=graph_score,
                    importance=importance,
                    confidence=confidence,
                    source_quality=source_quality,
                    access_count=access_count,
                    pinned=pinned,
                    memory_state=memory_state,
                    memory_type=memory_type,
                    memory_origin=memory_origin,
                    concepts=concepts.get(segment_id, []),
                    metadata={
                        "indexed_at": row["indexed_at"],
                        "last_accessed_at": row["last_accessed_at"],
                        "ranking": ranking.as_dict(),
                    },
                )
            )

        hits.sort(key=lambda hit: hit.score, reverse=True)

        selected: list[SearchHit] = []
        per_source: dict[str, int] = {}
        for hit in hits:
            if len(selected) >= requested:
                break
            if per_source.get(hit.source_id, 0) >= 3:
                continue
            selected.append(hit)
            per_source[hit.source_id] = per_source.get(hit.source_id, 0) + 1

        if record_access:
            self.repository.record_access([hit.segment_id for hit in selected])
        return selected

    def explain(self, query: str, top_k: int | None = None) -> list[dict]:
        return [
            {
                "segment_id": hit.segment_id,
                "source_path": hit.source_path,
                "title": hit.title,
                "heading": hit.heading,
                "score": hit.score,
                "weights": {
                    "importance": hit.importance,
                    "confidence": hit.confidence,
                    "source_quality": hit.source_quality,
                    "access_count": hit.access_count,
                    "pinned": hit.pinned,
                    "memory_state": int(hit.memory_state),
                    "memory_state_name": hit.memory_state.name,
                    "memory_type": int(hit.memory_type),
                    "memory_type_name": hit.memory_type.name,
                    "memory_origin": int(hit.memory_origin),
                    "memory_origin_name": hit.memory_origin.name,
                },
                "ranking": hit.metadata["ranking"],
            }
            for hit in self.search(query, top_k, record_access=False)
        ]

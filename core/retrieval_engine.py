from __future__ import annotations

from core.config import Settings
from core.models import SearchHit
from database.repositories import SQLiteRepository
from database.vector_memory import VectorMemory
from extraction.markdown_parser import extract_concepts


class RetrievalEngine:
    def __init__(self, settings: Settings, repository: SQLiteRepository, vectors: VectorMemory) -> None:
        self.settings = settings
        self.repository = repository
        self.vectors = vectors

    def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        top_k = top_k or self.settings.default_top_k
        vector_hits = self.vectors.search(query, max(40, top_k * 5))
        ids = [hit["segment_id"] for hit in vector_hits]
        metadata = self.repository.source_metadata(ids)
        concepts = self.repository.concepts_for(ids)
        lexical = self.repository.lexical_scores(query)
        graph = self.repository.graph_scores(extract_concepts(query, limit=10))
        hits: list[SearchHit] = []
        for item in vector_hits:
            sid = item["segment_id"]
            row = metadata.get(sid)
            if not row:
                continue
            vector_score = item["vector_score"]
            lexical_score = lexical.get(sid, 0.0)
            graph_score = graph.get(sid, 0.0)
            importance = float(row["importance"])
            score = (0.65 * vector_score + 0.20 * lexical_score + 0.10 * graph_score + 0.05 * min(1.0, importance / 2.0))
            hits.append(SearchHit(
                segment_id=sid,
                source_id=row["source_id"],
                source_path=row["source_path"],
                title=row["title"],
                heading=row["heading"],
                text=row["text"],
                score=score,
                vector_score=vector_score,
                lexical_score=lexical_score,
                graph_score=graph_score,
                importance=importance,
                concepts=concepts.get(sid, []),
                metadata={"indexed_at": row["indexed_at"]},
            ))
        hits.sort(key=lambda hit: hit.score, reverse=True)
        selected: list[SearchHit] = []
        per_source: dict[str, int] = {}
        for hit in hits:
            if len(selected) >= top_k:
                break
            if per_source.get(hit.source_id, 0) >= 3:
                continue
            selected.append(hit)
            per_source[hit.source_id] = per_source.get(hit.source_id, 0) + 1
        return selected

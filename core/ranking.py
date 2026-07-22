from __future__ import annotations

import math
from dataclasses import dataclass


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class RankingBreakdown:
    score: float
    vector: float
    lexical: float
    graph: float
    importance: float
    confidence: float
    source_quality: float
    access: float
    pinned: float

    def as_dict(self) -> dict[str, float]:
        return {
            "score": self.score,
            "vector": self.vector,
            "lexical": self.lexical,
            "graph": self.graph,
            "importance": self.importance,
            "confidence": self.confidence,
            "source_quality": self.source_quality,
            "access": self.access,
            "pinned": self.pinned,
        }


def rank_memory(
    *,
    vector_score: float,
    lexical_score: float,
    graph_score: float,
    importance: float,
    confidence: float,
    source_quality: float,
    access_count: int,
    pinned: bool,
) -> RankingBreakdown:
    """Combine retrieval relevance with persistent memory weighting.

    Relevance remains dominant, while learned state can promote trusted,
    important, frequently useful, or explicitly pinned memories.
    """
    vector = 0.52 * clamp(vector_score)
    lexical = 0.15 * clamp(lexical_score)
    graph = 0.08 * clamp(graph_score)
    importance_factor = 0.08 * clamp(importance / 2.0)
    confidence_factor = 0.05 * clamp(confidence)
    source_quality_factor = 0.04 * clamp(source_quality)
    access_factor = 0.03 * clamp(math.log1p(max(0, access_count)) / math.log(101))
    pinned_factor = 0.05 if pinned else 0.0

    score = clamp(
        vector
        + lexical
        + graph
        + importance_factor
        + confidence_factor
        + source_quality_factor
        + access_factor
        + pinned_factor
    )
    return RankingBreakdown(
        score=score,
        vector=vector,
        lexical=lexical,
        graph=graph,
        importance=importance_factor,
        confidence=confidence_factor,
        source_quality=source_quality_factor,
        access=access_factor,
        pinned=pinned_factor,
    )

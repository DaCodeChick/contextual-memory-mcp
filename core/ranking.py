from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


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
    recency: float
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
            "recency": self.recency,
            "pinned": self.pinned,
        }


def _recency_score(
    timestamp: datetime | str | None,
    *,
    evaluated_at: datetime,
    half_life_days: float,
) -> float:
    if timestamp is None:
        return 0.0
    value = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    age_days = max(
        0.0,
        (evaluated_at.astimezone(timezone.utc) - value.astimezone(timezone.utc)).total_seconds()
        / 86400,
    )
    return math.exp(-math.log(2.0) * age_days / half_life_days)


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
    last_accessed_at: datetime | str | None = None,
    indexed_at: datetime | str | None = None,
    evaluated_at: datetime | None = None,
    recency_half_life_days: float = 45.0,
) -> RankingBreakdown:
    """Blend relevance with persistent, explainable memory signals."""
    now = evaluated_at or datetime.now(timezone.utc)
    recency_timestamp = last_accessed_at or indexed_at

    vector = 0.51 * clamp(vector_score)
    lexical = 0.14 * clamp(lexical_score)
    graph = 0.08 * clamp(graph_score)
    importance_factor = 0.10 * clamp(importance / 2.0)
    confidence_factor = 0.05 * clamp(confidence)
    source_quality_factor = 0.04 * clamp(source_quality)
    access_factor = 0.03 * clamp(math.log1p(max(0, access_count)) / math.log(101))
    recency_factor = 0.03 * _recency_score(
        recency_timestamp,
        evaluated_at=now,
        half_life_days=recency_half_life_days,
    )
    pinned_factor = 0.05 if pinned else 0.0

    score = clamp(
        vector + lexical + graph + importance_factor + confidence_factor
        + source_quality_factor + access_factor + recency_factor + pinned_factor
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
        recency=recency_factor,
        pinned=pinned_factor,
    )

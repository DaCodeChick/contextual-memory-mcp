from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SourceDocument:
    source_id: str
    path: Path
    relative_path: str
    title: str
    content: str
    content_hash: str
    modified_ns: int
    size_bytes: int


@dataclass(slots=True)
class MemorySegment:
    segment_id: str
    source_id: str
    ordinal: int
    heading: str | None
    text: str
    char_start: int
    char_end: int
    identity_key: str
    content_hash: str
    importance: float = 1.0
    concepts: list[str] = field(default_factory=list)
    confidence: float = 1.0
    source_quality: float = 1.0


# Compatibility alias for the first prompt-specific prototype.
PromptSegment = MemorySegment


@dataclass(slots=True)
class SearchHit:
    segment_id: str
    source_id: str
    source_path: str
    title: str
    heading: str | None
    text: str
    score: float
    vector_score: float
    lexical_score: float
    graph_score: float
    importance: float
    confidence: float
    source_quality: float
    access_count: int
    pinned: bool
    concepts: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

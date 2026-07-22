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
class PromptSegment:
    segment_id: str
    source_id: str
    ordinal: int
    heading: str | None
    text: str
    char_start: int
    char_end: int
    importance: float = 1.0
    concepts: list[str] = field(default_factory=list)


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
    concepts: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

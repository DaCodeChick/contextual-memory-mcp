from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.enums import MemoryOrigin, MemoryState, MemoryType


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
    memory_state: MemoryState = MemoryState.ACTIVE
    memory_type: MemoryType = MemoryType.UNKNOWN
    memory_origin: MemoryOrigin = MemoryOrigin.UNKNOWN


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
    memory_state: MemoryState
    memory_type: MemoryType
    memory_origin: MemoryOrigin
    concepts: list[str]
    store_id: str
    store_priority: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def memory_ref(self) -> str:
        return f"{self.store_id}:{self.segment_id}"

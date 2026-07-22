from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

sys.modules.setdefault("chromadb", types.ModuleType("chromadb"))
sentence_transformers = types.ModuleType("sentence_transformers")
sentence_transformers.SentenceTransformer = object
sys.modules.setdefault("sentence_transformers", sentence_transformers)

from core.config import Settings
from core.enums import MemoryOrigin, MemoryState, MemoryType
from core.ingestion_service import IngestionService
from database.repositories import SQLiteRepository


class FakeVectors:
    def __init__(self) -> None:
        self.upserts: list[tuple[object, list[object], list[str]]] = []

    def upsert_document(self, doc, segments, deleted_ids) -> None:  # noqa: ANN001
        self.upserts.append((doc, list(segments), list(deleted_ids)))


def test_automatic_user_memory_uses_neutral_importance(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, automatic_memory_importance=0.5)
    repository = SQLiteRepository(settings.sqlite_path)
    repository.initialize()
    vectors = FakeVectors()
    ingestion = IngestionService(settings, repository, vectors)  # type: ignore[arg-type]

    result = ingestion.remember(
        title="Stable identity",
        text="The user's name is Schala.",
        memory_state=MemoryState.ACTIVE,
        memory_type=MemoryType.FACT,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )

    segment_id = vectors.upserts[0][1][0].segment_id
    metadata = repository.source_metadata([segment_id])[segment_id]
    assert result["importance"] == 0.5
    assert metadata["importance"] == 0.5
    assert metadata["confidence"] == 1.0
    assert metadata["source_quality"] == 1.0


def test_automatic_memory_accepts_explicit_scoring(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    repository = SQLiteRepository(settings.sqlite_path)
    repository.initialize()
    vectors = FakeVectors()
    ingestion = IngestionService(settings, repository, vectors)  # type: ignore[arg-type]

    result = ingestion.remember(
        title="Candidate anecdote",
        text="The user shared a one-off autobiographical anecdote.",
        memory_state=MemoryState.CANDIDATE,
        memory_type=MemoryType.OBSERVATION,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
        importance=0.35,
        confidence=0.95,
        source_quality=1.0,
    )

    assert result["memory_state"] == int(MemoryState.CANDIDATE)
    assert result["importance"] == 0.35
    assert result["confidence"] == 0.95


@pytest.mark.parametrize(
    ("field", "value"),
    [("importance", 2.1), ("confidence", -0.1), ("source_quality", 1.1)],
)
def test_automatic_memory_rejects_invalid_scores(
    tmp_path: Path, field: str, value: float
) -> None:
    settings = Settings(data_dir=tmp_path)
    repository = SQLiteRepository(settings.sqlite_path)
    repository.initialize()
    ingestion = IngestionService(settings, repository, FakeVectors())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        ingestion.remember(title="Invalid", text="Invalid", **{field: value})


def test_mcp_policy_requires_silent_automatic_storage() -> None:
    server_path = Path(__file__).parents[1] / "mcp_server" / "server.py"
    module = ast.parse(server_path.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MCP_INSTRUCTIONS"
            for target in node.targets
        )
    )
    value = assignment.value
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        value = value.func.value
    instructions = ast.literal_eval(value)

    assert "Silently and automatically call store_memory" in instructions
    assert "must not ask for permission" in instructions
    assert "does not need to" in instructions

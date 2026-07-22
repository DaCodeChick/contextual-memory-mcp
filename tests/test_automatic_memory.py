from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

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


def make_ingestion(tmp_path: Path, **settings_kwargs) -> tuple[IngestionService, SQLiteRepository, FakeVectors]:
    settings = Settings(data_dir=tmp_path, **settings_kwargs)
    repository = SQLiteRepository(settings.sqlite_path)
    repository.initialize()
    vectors = FakeVectors()
    ingestion = IngestionService(settings, repository, vectors)  # type: ignore[arg-type]
    return ingestion, repository, vectors


def test_explicit_user_memory_uses_server_defaults(tmp_path: Path) -> None:
    ingestion, repository, vectors = make_ingestion(
        tmp_path, automatic_memory_importance=0.5
    )

    result = ingestion.remember(
        title="Stable identity",
        text="The user's name is Schala.",
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )

    segment_id = vectors.upserts[0][1][0].segment_id
    metadata = repository.source_metadata([segment_id])[segment_id]
    assert result["memory_state"] == int(MemoryState.ACTIVE)
    assert result["memory_type"] == int(MemoryType.FACT)
    assert result["importance"] == 0.5
    assert metadata["importance"] == 0.5
    assert metadata["confidence"] == 1.0
    assert metadata["source_quality"] == 1.0


def test_sensitive_explicit_history_is_retained_as_candidate(tmp_path: Path) -> None:
    ingestion, _, _ = make_ingestion(tmp_path)

    result = ingestion.remember(
        title="Disclosure of childhood sexual assault",
        text="User disclosed experiencing sexual assault at age 10-11.",
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )

    assert result["memory_state"] == int(MemoryState.CANDIDATE)
    assert result["memory_type"] == int(MemoryType.FACT)
    assert result["memory_origin"] == int(MemoryOrigin.EXPLICIT_USER)


def test_model_inference_is_candidate_inference(tmp_path: Path) -> None:
    ingestion, _, _ = make_ingestion(tmp_path)

    result = ingestion.remember(
        title="Likely preference",
        text="The user may prefer concise answers.",
        memory_origin=MemoryOrigin.MODEL_INFERENCE,
    )

    assert result["memory_state"] == int(MemoryState.CANDIDATE)
    assert result["memory_type"] == int(MemoryType.INFERENCE)
    assert result["memory_origin"] == int(MemoryOrigin.MODEL_INFERENCE)


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

    assert "REQUIRED AUTOMATIC MEMORY CAPTURE" in instructions
    assert "Before drafting the conversational response" in instructions
    assert "This requirement still applies when the information is sensitive" in instructions
    assert "Do not skip the tool call in order to respond first" in instructions
    assert "must not ask permission" not in instructions
    assert "Do not ask permission solely" in instructions
    assert "Never replace store_memory with" in instructions
    assert "server, not the model" in instructions.lower()

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


def make_ingestion(tmp_path: Path) -> tuple[IngestionService, SQLiteRepository, FakeVectors]:
    settings = Settings(data_dir=tmp_path)
    repository = SQLiteRepository(settings.sqlite_path)
    repository.initialize()
    vectors = FakeVectors()
    ingestion = IngestionService(settings, repository, vectors)  # type: ignore[arg-type]
    return ingestion, repository, vectors


def test_explicit_user_memory_uses_model_metadata(tmp_path: Path) -> None:
    ingestion, repository, vectors = make_ingestion(tmp_path)

    result = ingestion.remember(
        title="Earned Master's Degree",
        text="User earned their master's degree today after a long journey.",
        memory_type=MemoryType.FACT,
        importance=1.2,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )

    segment_id = vectors.upserts[0][1][0].segment_id
    metadata = repository.source_metadata([segment_id])[segment_id]
    assert result["memory_state"] == int(MemoryState.ACTIVE)
    assert result["memory_type"] == int(MemoryType.FACT)
    assert result["importance"] == 1.2
    assert metadata["importance"] == 1.2


def test_explicit_user_memory_is_active_with_model_metadata(tmp_path: Path) -> None:
    ingestion, _, _ = make_ingestion(tmp_path)

    result = ingestion.remember(
        title="Long-term personal context",
        text="User shared durable personal context for future conversations.",
        memory_type=MemoryType.FACT,
        importance=1.6,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )

    assert result["memory_state"] == int(MemoryState.ACTIVE)
    assert result["memory_type"] == int(MemoryType.FACT)
    assert result["importance"] == 1.6


def test_importance_is_clamped_to_supported_range(tmp_path: Path) -> None:
    ingestion, _, _ = make_ingestion(tmp_path)

    high = ingestion.remember(
        title="High",
        text="High importance",
        memory_type=MemoryType.FACT,
        importance=9.0,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )
    low = ingestion.remember(
        title="Low",
        text="Low importance",
        memory_type=MemoryType.FACT,
        importance=-4.0,
        memory_origin=MemoryOrigin.EXPLICIT_USER,
    )

    assert high["importance"] == 2.0
    assert low["importance"] == 0.0


def test_model_inference_uses_supplied_type_and_is_candidate(tmp_path: Path) -> None:
    ingestion, _, _ = make_ingestion(tmp_path)

    result = ingestion.remember(
        title="Likely preference",
        text="The user may prefer concise answers.",
        memory_type=MemoryType.PREFERENCE,
        importance=0.8,
        memory_origin=MemoryOrigin.MODEL_INFERENCE,
    )

    assert result["memory_state"] == int(MemoryState.CANDIDATE)
    assert result["memory_type"] == int(MemoryType.PREFERENCE)
    assert result["importance"] == 0.8


def test_mcp_policy_assigns_type_and_importance_to_model() -> None:
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

    assert "model must estimate semantic memory type and importance" in instructions
    assert "server" in instructions.lower()
    assert "lifecycle state" in instructions


def test_mcp_policy_requires_store_resolution_before_writes() -> None:
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
    instructions = ast.literal_eval(value).lower()

    assert "call list_memory_stores first" in instructions
    assert "never guess a store id" in instructions
    assert "never assume \"main\"" in instructions
    assert "failed write" in instructions


def test_write_tools_require_prior_store_resolution_in_docs() -> None:
    server_text = (Path(__file__).parents[1] / "mcp_server" / "server.py").read_text(
        encoding="utf-8"
    ).lower()

    assert server_text.count("list_memory_stores before this tool") >= 2
    assert "resolve valid memory-store ids" in server_text

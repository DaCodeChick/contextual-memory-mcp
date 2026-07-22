from datetime import datetime, timezone
from pathlib import Path

from core.importance import ImportancePolicy
from core.importance_service import ImportanceService
from core.models import MemorySegment, SourceDocument
from database.repositories import SQLiteRepository


def test_importance_service_persists_reinforcement(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "memory.sqlite3")
    repo.initialize()
    doc = SourceDocument("src", Path("a.md"), "a.md", "A", "x", "hash", 0, 1)
    segment = MemorySegment(
        "seg", "src", 0, None, "x", 0, 1, "identity", "hash"
    )
    repo.reconcile_document(doc, [segment])
    repo.record_access(["seg"])

    result = ImportanceService(repo, ImportancePolicy(access_gain=0.2)).run(
        evaluated_at=datetime(2026, 7, 22, tzinfo=timezone.utc)
    )
    metadata = repo.source_metadata(["seg"])["seg"]

    assert result.adjusted == 1
    assert metadata["importance"] == 1.2
    assert metadata["importance_access_count"] == 1
    assert metadata["importance_reason"] == 2


def test_importance_dry_run_does_not_mutate(tmp_path: Path) -> None:
    repo = SQLiteRepository(tmp_path / "memory.sqlite3")
    repo.initialize()
    doc = SourceDocument("src", Path("a.md"), "a.md", "A", "x", "hash", 0, 1)
    repo.reconcile_document(
        doc,
        [MemorySegment("seg", "src", 0, None, "x", 0, 1, "identity", "hash")],
    )
    repo.record_access(["seg"])

    result = ImportanceService(repo).run(apply=False)
    metadata = repo.source_metadata(["seg"])["seg"]

    assert result.adjusted == 0
    assert result.decisions[0].changes_importance
    assert metadata["importance"] == 1.0
    assert metadata["importance_access_count"] == 0

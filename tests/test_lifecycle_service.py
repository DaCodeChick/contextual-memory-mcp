from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.enums import LifecycleReason, MemoryState
from core.lifecycle import LifecyclePolicy
from core.lifecycle_service import LifecycleService
from core.models import MemorySegment, SourceDocument
from database.repositories import SQLiteRepository


def make_repository(tmp_path: Path) -> SQLiteRepository:
    repo = SQLiteRepository(tmp_path / "memory.sqlite3")
    repo.initialize()
    return repo


def add_memory(
    repo: SQLiteRepository,
    segment_id: str,
    *,
    state: MemoryState,
    importance: float,
) -> None:
    doc = SourceDocument(
        f"src_{segment_id}",
        Path(f"{segment_id}.md"),
        f"{segment_id}.md",
        segment_id,
        "content",
        "hash",
        0,
        7,
    )
    segment = MemorySegment(
        segment_id=segment_id,
        source_id=doc.source_id,
        ordinal=0,
        heading=None,
        text="content",
        char_start=0,
        char_end=7,
        identity_key="memory",
        content_hash="hash",
        importance=importance,
        memory_state=state,
    )
    repo.reconcile_document(doc, [segment], source_kind="memory")


def test_service_promotes_candidate_and_records_audit_metadata(
    tmp_path: Path,
) -> None:
    repo = make_repository(tmp_path)
    add_memory(
        repo,
        "candidate",
        state=MemoryState.CANDIDATE,
        importance=1.8,
    )
    evaluated_at = datetime(2026, 7, 22, tzinfo=timezone.utc)

    decision = LifecycleService(repo).evaluate_segment(
        "candidate",
        evaluated_at=evaluated_at,
        apply=True,
    )
    metadata = repo.lifecycle_metadata("candidate")

    assert decision.target_state is MemoryState.ACTIVE
    assert metadata["memory_state"] == int(MemoryState.ACTIVE)
    assert metadata["lifecycle_reason"] == int(LifecycleReason.IMPORTANCE)
    assert metadata["state_changed_at"] == evaluated_at.isoformat()
    assert metadata["promoted_at"] == evaluated_at.isoformat()
    assert metadata["archived_at"] is None


def test_service_archives_inactive_memory(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    add_memory(
        repo,
        "inactive",
        state=MemoryState.ACTIVE,
        importance=0.2,
    )
    evaluated_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    with repo.connect() as db:
        db.execute(
            "UPDATE segments SET last_accessed_at=? WHERE segment_id=?",
            (
                (evaluated_at - timedelta(days=100)).isoformat(),
                "inactive",
            ),
        )

    result = LifecycleService(repo).run(evaluated_at=evaluated_at)
    metadata = repo.lifecycle_metadata("inactive")

    assert result.evaluated == 1
    assert result.changed == 1
    assert metadata["memory_state"] == int(MemoryState.ARCHIVED)
    assert metadata["lifecycle_reason"] == int(LifecycleReason.INACTIVITY)
    assert metadata["archived_at"] == evaluated_at.isoformat()


def test_dry_run_does_not_mutate_storage(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    add_memory(
        repo,
        "candidate",
        state=MemoryState.CANDIDATE,
        importance=2.0,
    )

    result = LifecycleService(repo).run(apply=False)

    assert result.changed == 0
    assert result.decisions[0].changes_state
    assert repo.lifecycle_metadata("candidate")["memory_state"] == int(
        MemoryState.CANDIDATE
    )


def test_stale_decision_is_rejected(tmp_path: Path) -> None:
    repo = make_repository(tmp_path)
    add_memory(
        repo,
        "candidate",
        state=MemoryState.CANDIDATE,
        importance=2.0,
    )
    service = LifecycleService(repo, LifecyclePolicy())
    decision = service.evaluate_segment("candidate")
    repo.set_segment_lifecycle(
        "candidate",
        memory_state=MemoryState.REJECTED,
    )

    with pytest.raises(RuntimeError, match="changed after evaluation"):
        repo.apply_lifecycle_decision("candidate", decision)

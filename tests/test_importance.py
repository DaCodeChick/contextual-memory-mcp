from datetime import datetime, timedelta, timezone

from core.enums import ImportanceReason, MemoryState
from core.importance import ImportancePolicy, ImportanceSnapshot


def snapshot(**overrides: object) -> ImportanceSnapshot:
    values = {
        "segment_id": "memory",
        "importance": 1.0,
        "access_count": 0,
        "evaluated_access_count": 0,
        "pinned": False,
        "memory_state": MemoryState.ACTIVE,
        "importance_updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_accessed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ImportanceSnapshot(**values)  # type: ignore[arg-type]


def test_new_accesses_reinforce_importance() -> None:
    decision = ImportancePolicy(access_gain=0.1).evaluate(
        snapshot(access_count=3),
        evaluated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert decision.target_importance == 1.3
    assert decision.reason_code is ImportanceReason.ACCESS_REINFORCEMENT
    assert decision.target_evaluated_access_count == 3


def test_inactivity_decays_importance_incrementally() -> None:
    decision = ImportancePolicy(
        decay_grace_days=30,
        decay_per_30_days=0.1,
    ).evaluate(
        snapshot(),
        evaluated_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
    )
    assert decision.target_importance == 0.9
    assert decision.reason_code is ImportanceReason.INACTIVITY_DECAY


def test_pinned_memory_does_not_decay() -> None:
    decision = ImportancePolicy(decay_per_30_days=1.0).evaluate(
        snapshot(pinned=True),
        evaluated_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    assert decision.target_importance == 1.0
    assert not decision.changes_importance

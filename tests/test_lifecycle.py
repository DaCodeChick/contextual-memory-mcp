from datetime import datetime, timedelta, timezone

import pytest

from core.enums import LifecycleAction, MemoryState
from core.lifecycle import LifecyclePolicy, LifecycleSnapshot


def snapshot(**overrides: object) -> LifecycleSnapshot:
    values: dict[str, object] = {
        "memory_state": MemoryState.CANDIDATE,
        "importance": 1.0,
        "confidence": 1.0,
        "source_quality": 1.0,
        "access_count": 0,
    }
    values.update(overrides)
    return LifecycleSnapshot(**values)  # type: ignore[arg-type]


def test_candidate_promotes_from_importance() -> None:
    decision = LifecyclePolicy().evaluate(snapshot(importance=1.5))

    assert decision.action is LifecycleAction.PROMOTE
    assert decision.target_state is MemoryState.ACTIVE
    assert decision.changes_state


def test_candidate_promotes_after_repeated_access() -> None:
    decision = LifecyclePolicy().evaluate(snapshot(access_count=3))

    assert decision.action is LifecycleAction.PROMOTE
    assert decision.target_state is MemoryState.ACTIVE


def test_low_confidence_blocks_candidate_promotion() -> None:
    decision = LifecyclePolicy().evaluate(
        snapshot(importance=2.0, access_count=100, confidence=0.4)
    )

    assert decision.action is LifecycleAction.KEEP
    assert decision.target_state is MemoryState.CANDIDATE


def test_pinned_memory_is_promoted_regardless_of_score() -> None:
    decision = LifecyclePolicy().evaluate(
        snapshot(confidence=0.0, source_quality=0.0, pinned=True)
    )

    assert decision.action is LifecycleAction.PROMOTE
    assert decision.target_state is MemoryState.ACTIVE


def test_low_importance_inactive_memory_is_archived() -> None:
    evaluated_at = datetime(2026, 7, 22, tzinfo=timezone.utc)
    decision = LifecyclePolicy().evaluate(
        snapshot(
            memory_state=MemoryState.ACTIVE,
            importance=0.2,
            last_accessed_at=evaluated_at - timedelta(days=91),
        ),
        evaluated_at=evaluated_at,
    )

    assert decision.action is LifecycleAction.ARCHIVE
    assert decision.target_state is MemoryState.ARCHIVED


def test_active_memory_without_access_timestamp_is_not_archived() -> None:
    decision = LifecyclePolicy().evaluate(
        snapshot(memory_state=MemoryState.ACTIVE, importance=0.0)
    )

    assert decision.action is LifecycleAction.KEEP
    assert decision.target_state is MemoryState.ACTIVE


def test_rejected_memory_is_never_automatically_changed() -> None:
    decision = LifecyclePolicy().evaluate(
        snapshot(memory_state=MemoryState.REJECTED, pinned=True)
    )

    assert decision.action is LifecycleAction.KEEP
    assert decision.target_state is MemoryState.REJECTED


def test_policy_rejects_overlapping_thresholds() -> None:
    with pytest.raises(ValueError):
        LifecyclePolicy(
            promotion_importance=1.0,
            archive_importance=1.0,
        )

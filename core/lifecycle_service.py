from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core.lifecycle import LifecycleDecision, LifecyclePolicy, LifecycleSnapshot
from database.repositories import SQLiteRepository


@dataclass(frozen=True, slots=True)
class LifecycleRunResult:
    """Summary of one repository-backed lifecycle evaluation pass."""

    evaluated: int
    changed: int
    decisions: tuple[LifecycleDecision, ...]


class LifecycleService:
    """Evaluate stored memories and atomically apply accepted transitions."""

    def __init__(
        self,
        repository: SQLiteRepository,
        policy: LifecyclePolicy | None = None,
    ) -> None:
        self.repository = repository
        self.policy = policy or LifecyclePolicy()

    def evaluate_segment(
        self,
        segment_id: str,
        *,
        evaluated_at: datetime | None = None,
        apply: bool = False,
    ) -> LifecycleDecision:
        row = self.repository.lifecycle_metadata(segment_id)
        decision = self.policy.evaluate(
            self._snapshot(row),
            evaluated_at=evaluated_at,
        )
        if apply and decision.changes_state:
            self.repository.apply_lifecycle_decision(
                segment_id,
                decision,
                changed_at=evaluated_at,
            )
        return decision

    def run(
        self,
        *,
        evaluated_at: datetime | None = None,
        apply: bool = True,
    ) -> LifecycleRunResult:
        when = evaluated_at or datetime.now(timezone.utc)
        decisions: list[LifecycleDecision] = []
        changed = 0

        for row in self.repository.lifecycle_candidates():
            decision = self.policy.evaluate(
                self._snapshot(row),
                evaluated_at=when,
            )
            decisions.append(decision)
            if apply and decision.changes_state:
                self.repository.apply_lifecycle_decision(
                    str(row["segment_id"]),
                    decision,
                    changed_at=when,
                )
                changed += 1

        return LifecycleRunResult(
            evaluated=len(decisions),
            changed=changed,
            decisions=tuple(decisions),
        )

    @staticmethod
    def _snapshot(row: dict) -> LifecycleSnapshot:
        last_accessed = row.get("last_accessed_at")
        return LifecycleSnapshot(
            memory_state=row["memory_state"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            source_quality=float(row["source_quality"]),
            access_count=int(row["access_count"]),
            pinned=bool(row["pinned"]),
            last_accessed_at=(
                datetime.fromisoformat(str(last_accessed))
                if last_accessed
                else None
            ),
        )

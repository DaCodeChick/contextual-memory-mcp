from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core.enums import MemoryState
from core.importance import ImportanceDecision, ImportancePolicy, ImportanceSnapshot
from database.repositories import SQLiteRepository


@dataclass(frozen=True, slots=True)
class ImportanceRunResult:
    evaluated: int
    adjusted: int
    decisions: tuple[ImportanceDecision, ...]
    changed_segment_ids: tuple[str, ...]


class ImportanceService:
    def __init__(self, repository: SQLiteRepository, policy: ImportancePolicy | None = None) -> None:
        self.repository = repository
        self.policy = policy or ImportancePolicy()

    def run(self, *, evaluated_at: datetime | None = None, apply: bool = True) -> ImportanceRunResult:
        when = evaluated_at or datetime.now(timezone.utc)
        decisions: list[ImportanceDecision] = []
        changed: list[str] = []
        for row in self.repository.importance_candidates():
            decision = self.policy.evaluate(self._snapshot(row), evaluated_at=when)
            decisions.append(decision)
            if apply and decision.requires_persistence:
                self.repository.apply_importance_decision(decision, changed_at=when)
                if decision.changes_importance:
                    changed.append(decision.segment_id)
        return ImportanceRunResult(
            evaluated=len(decisions),
            adjusted=len(changed),
            decisions=tuple(decisions),
            changed_segment_ids=tuple(changed),
        )

    @staticmethod
    def _snapshot(row: dict) -> ImportanceSnapshot:
        def parsed(name: str):
            value = row.get(name)
            return datetime.fromisoformat(str(value)) if value else None
        return ImportanceSnapshot(
            segment_id=str(row["segment_id"]),
            importance=float(row["importance"]),
            access_count=int(row["access_count"]),
            evaluated_access_count=int(row["importance_access_count"]),
            pinned=bool(row["pinned"]),
            memory_state=MemoryState(int(row["memory_state"])),
            importance_updated_at=parsed("importance_updated_at"),
            last_accessed_at=parsed("last_accessed_at"),
        )

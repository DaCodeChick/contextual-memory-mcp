from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.enums import ImportanceReason, MemoryState


@dataclass(frozen=True, slots=True)
class ImportanceSnapshot:
    segment_id: str
    importance: float
    access_count: int
    evaluated_access_count: int
    pinned: bool
    memory_state: MemoryState
    importance_updated_at: datetime | None
    last_accessed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ImportanceDecision:
    segment_id: str
    previous_importance: float
    target_importance: float
    previous_evaluated_access_count: int
    target_evaluated_access_count: int
    reason_code: ImportanceReason
    reason: str

    @property
    def changes_importance(self) -> bool:
        return abs(self.previous_importance - self.target_importance) > 1e-12

    @property
    def requires_persistence(self) -> bool:
        return (
            self.changes_importance
            or self.previous_evaluated_access_count
            != self.target_evaluated_access_count
        )


@dataclass(frozen=True, slots=True)
class ImportancePolicy:
    """Reinforce useful memories and gradually decay inactive ones."""

    access_gain: float = 0.05
    decay_per_30_days: float = 0.05
    decay_grace_days: int = 30
    minimum_importance: float = 0.0
    maximum_importance: float = 2.0

    def __post_init__(self) -> None:
        if self.access_gain < 0:
            raise ValueError("access_gain must be non-negative")
        if self.decay_per_30_days < 0:
            raise ValueError("decay_per_30_days must be non-negative")
        if self.decay_grace_days < 0:
            raise ValueError("decay_grace_days must be non-negative")
        if self.minimum_importance < 0:
            raise ValueError("minimum_importance must be non-negative")
        if self.maximum_importance > 2.0:
            raise ValueError("maximum_importance must not exceed 2.0")
        if self.minimum_importance > self.maximum_importance:
            raise ValueError("minimum_importance must not exceed maximum_importance")

    def evaluate(
        self,
        memory: ImportanceSnapshot,
        *,
        evaluated_at: datetime | None = None,
    ) -> ImportanceDecision:
        now = evaluated_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)

        new_accesses = max(0, memory.access_count - memory.evaluated_access_count)
        reinforcement = new_accesses * self.access_gain
        decay = 0.0

        if not memory.pinned and memory.memory_state is not MemoryState.REJECTED:
            updated_at = self._utc(memory.importance_updated_at) or now
            inactivity_anchor = self._utc(memory.last_accessed_at) or updated_at
            decay_start = max(
                updated_at,
                inactivity_anchor + timedelta(days=self.decay_grace_days),
            )
            elapsed_days = max(0.0, (now - decay_start).total_seconds() / 86400)
            decay = (elapsed_days / 30.0) * self.decay_per_30_days

        target = min(
            self.maximum_importance,
            max(self.minimum_importance, memory.importance + reinforcement - decay),
        )

        if reinforcement and decay:
            reason_code = ImportanceReason.MIXED
            reason = "access reinforcement and inactivity decay were applied"
        elif reinforcement:
            reason_code = ImportanceReason.ACCESS_REINFORCEMENT
            reason = f"{new_accesses} new access event(s) reinforced the memory"
        elif decay:
            reason_code = ImportanceReason.INACTIVITY_DECAY
            reason = "elapsed inactivity reduced memory importance"
        else:
            reason_code = ImportanceReason.NONE
            reason = "importance remains unchanged"

        return ImportanceDecision(
            segment_id=memory.segment_id,
            previous_importance=memory.importance,
            target_importance=round(target, 6),
            previous_evaluated_access_count=memory.evaluated_access_count,
            target_evaluated_access_count=memory.access_count,
            reason_code=reason_code,
            reason=reason,
        )

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

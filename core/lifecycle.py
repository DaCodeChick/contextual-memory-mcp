from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.enums import LifecycleAction, MemoryState


@dataclass(frozen=True, slots=True)
class LifecycleSnapshot:
    """The policy-relevant state of one memory at evaluation time."""

    memory_state: MemoryState
    importance: float
    confidence: float
    source_quality: float
    access_count: int
    pinned: bool = False
    last_accessed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    """A side-effect-free lifecycle recommendation."""

    action: LifecycleAction
    current_state: MemoryState
    target_state: MemoryState
    reason: str

    @property
    def changes_state(self) -> bool:
        return self.current_state != self.target_state


@dataclass(frozen=True, slots=True)
class LifecyclePolicy:
    """Configurable rules for promotion and archival.

    This class deliberately does not read from or write to storage. A later
    lifecycle service can evaluate repository rows with this policy and apply
    accepted decisions in one auditable transaction.
    """

    promotion_importance: float = 1.5
    promotion_access_count: int = 3
    minimum_confidence: float = 0.6
    minimum_source_quality: float = 0.5
    archive_importance: float = 0.35
    archive_after_days: int = 90

    def __post_init__(self) -> None:
        for name, value, low, high in (
            ("promotion_importance", self.promotion_importance, 0.0, 2.0),
            ("minimum_confidence", self.minimum_confidence, 0.0, 1.0),
            ("minimum_source_quality", self.minimum_source_quality, 0.0, 1.0),
            ("archive_importance", self.archive_importance, 0.0, 2.0),
        ):
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        if self.promotion_access_count < 0:
            raise ValueError("promotion_access_count must be non-negative")
        if self.archive_after_days < 0:
            raise ValueError("archive_after_days must be non-negative")
        if self.archive_importance >= self.promotion_importance:
            raise ValueError(
                "archive_importance must be lower than promotion_importance"
            )

    def evaluate(
        self,
        memory: LifecycleSnapshot,
        *,
        evaluated_at: datetime | None = None,
    ) -> LifecycleDecision:
        """Return a recommendation without mutating the memory."""
        current = MemoryState(memory.memory_state)

        if current is MemoryState.REJECTED:
            return self._keep(current, "rejected memories require manual review")

        if memory.pinned:
            if current is MemoryState.ACTIVE:
                return self._keep(current, "pinned memory remains active")
            return LifecycleDecision(
                LifecycleAction.PROMOTE,
                current,
                MemoryState.ACTIVE,
                "pinned memory is always eligible for active recall",
            )

        if current is MemoryState.CANDIDATE:
            return self._evaluate_candidate(memory)

        if current is MemoryState.ACTIVE:
            return self._evaluate_active(memory, evaluated_at=evaluated_at)

        return self._keep(current, "archived memories are not auto-reactivated")

    def _evaluate_candidate(
        self,
        memory: LifecycleSnapshot,
    ) -> LifecycleDecision:
        if memory.confidence < self.minimum_confidence:
            return self._keep(
                MemoryState.CANDIDATE,
                "confidence is below the promotion threshold",
            )
        if memory.source_quality < self.minimum_source_quality:
            return self._keep(
                MemoryState.CANDIDATE,
                "source quality is below the promotion threshold",
            )

        important = memory.importance >= self.promotion_importance
        repeated = memory.access_count >= self.promotion_access_count
        if important or repeated:
            reason = (
                "importance reached the promotion threshold"
                if important
                else "repeated access reached the promotion threshold"
            )
            return LifecycleDecision(
                LifecycleAction.PROMOTE,
                MemoryState.CANDIDATE,
                MemoryState.ACTIVE,
                reason,
            )

        return self._keep(
            MemoryState.CANDIDATE,
            "candidate has not accumulated enough evidence",
        )

    def _evaluate_active(
        self,
        memory: LifecycleSnapshot,
        *,
        evaluated_at: datetime | None,
    ) -> LifecycleDecision:
        if memory.importance > self.archive_importance:
            return self._keep(
                MemoryState.ACTIVE,
                "importance remains above the archival threshold",
            )
        if memory.last_accessed_at is None:
            return self._keep(
                MemoryState.ACTIVE,
                "no access timestamp is available for archival",
            )

        now = evaluated_at or datetime.now(timezone.utc)
        last_accessed = memory.last_accessed_at
        if last_accessed.tzinfo is None:
            last_accessed = last_accessed.replace(tzinfo=timezone.utc)
        inactive_for = now - last_accessed.astimezone(timezone.utc)
        if inactive_for < timedelta(days=self.archive_after_days):
            return self._keep(
                MemoryState.ACTIVE,
                "memory has not been inactive long enough",
            )

        return LifecycleDecision(
            LifecycleAction.ARCHIVE,
            MemoryState.ACTIVE,
            MemoryState.ARCHIVED,
            "low-importance memory exceeded the inactivity window",
        )

    @staticmethod
    def _keep(state: MemoryState, reason: str) -> LifecycleDecision:
        return LifecycleDecision(
            LifecycleAction.KEEP,
            state,
            state,
            reason,
        )

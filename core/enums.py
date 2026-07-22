from __future__ import annotations

from enum import IntEnum
from typing import TypeVar


class MemoryState(IntEnum):
    """Lifecycle state for a stored memory."""

    CANDIDATE = 0
    ACTIVE = 1
    ARCHIVED = 2
    REJECTED = 3


class LifecycleAction(IntEnum):
    """Action recommended by a lifecycle policy."""

    KEEP = 0
    PROMOTE = 1
    ARCHIVE = 2


class MemoryType(IntEnum):
    """Domain-independent semantic category for a memory."""

    UNKNOWN = 0
    PREFERENCE = 1
    FACT = 2
    RELATIONSHIP = 3
    PROJECT = 4
    SKILL = 5
    PROCEDURE = 6
    OBSERVATION = 7
    INFERENCE = 8


class MemoryOrigin(IntEnum):
    """How a memory entered the system."""

    UNKNOWN = 0
    EXPLICIT_USER = 1
    IMPORTED_FILE = 2
    GENERATED_SUMMARY = 3
    MODEL_INFERENCE = 4
    SPECIALTY = 5


EnumT = TypeVar("EnumT", bound=IntEnum)


def coerce_enum(enum_type: type[EnumT], value: int | IntEnum) -> EnumT:
    """Validate an integer-backed enum value and return its typed member."""
    try:
        return enum_type(int(value))
    except (TypeError, ValueError) as exc:
        choices = ", ".join(
            f"{member.value}={member.name}" for member in enum_type
        )
        raise ValueError(
            f"Invalid {enum_type.__name__} value {value!r}; expected {choices}"
        ) from exc

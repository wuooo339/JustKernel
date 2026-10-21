"""Task kinds and lifecycle states."""

from __future__ import annotations

from enum import StrEnum


# ---- TaskKind ---------------------------------------------------------------
class TaskKind(StrEnum):
    GENERATE = "GENERATE"
    OPTIMIZE = "OPTIMIZE"
    TEST = "TEST"
    PROFILE = "PROFILE"


# ---- TaskState --------------------------------------------------------------
class TaskState(StrEnum):
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL_TASK_STATES = frozenset(
    {
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.INTERRUPTED,
    }
)

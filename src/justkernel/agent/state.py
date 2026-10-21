"""Agent roles and lifecycle states."""

from __future__ import annotations

from enum import StrEnum


# ---- Role -------------------------------------------------------------------
class Role(StrEnum):
    SUPERVISOR = "SUPERVISOR"
    CONSULTANT = "CONSULTANT"
    MENTOR = "MENTOR"
    OPTIMIZER = "OPTIMIZER"
    TESTER = "TESTER"
    PROFILER = "PROFILER"


WORKER_ROLES = frozenset({Role.OPTIMIZER, Role.TESTER, Role.PROFILER})


# ---- AgentState -------------------------------------------------------------
class AgentState(StrEnum):
    CREATED = "CREATED"
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CLOSED = "CLOSED"

"""Testing and hardware lease enums."""

from __future__ import annotations

from enum import StrEnum


# ---- TestRecordKind ---------------------------------------------------------
class TestRecordKind(StrEnum):
    TEST = "TEST"
    PROFILE = "PROFILE"


# ---- TestOutcome ------------------------------------------------------------
class TestOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


# ---- TestCoverage -----------------------------------------------------------
class TestCoverage(StrEnum):
    FULL = "FULL"
    SUBSET = "SUBSET"
    NONE = "NONE"


# ---- LeaseState -------------------------------------------------------------
class LeaseState(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"

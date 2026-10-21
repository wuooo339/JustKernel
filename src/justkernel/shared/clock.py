"""Clock protocols and deterministic test clock."""

from __future__ import annotations

import time
from typing import Protocol

from justkernel.shared.errors import InvalidClockError


# ---- Clock ------------------------------------------------------------------
class Clock(Protocol):
    """Source of Unix epoch milliseconds."""

    def now_ms(self) -> int: ...


# ---- SystemClock ------------------------------------------------------------
class SystemClock:
    """Wall clock in Unix epoch milliseconds."""

    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


# ---- FakeClock --------------------------------------------------------------
class FakeClock:
    """Deterministic clock for tests."""

    def __init__(self, now_ms: int = 0) -> None:
        self._now_ms = 0
        self.set(now_ms)

    def now_ms(self) -> int:
        return self._now_ms

    def set(self, now_ms: int) -> None:
        if now_ms < 0:
            raise InvalidClockError("clock time must be non-negative")
        self._now_ms = now_ms

    def advance(self, milliseconds: int) -> int:
        if milliseconds < 0:
            raise InvalidClockError("clock advance must be non-negative")
        self._now_ms += milliseconds
        return self._now_ms

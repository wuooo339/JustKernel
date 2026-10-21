from __future__ import annotations

import pytest

from justkernel.shared.clock import FakeClock, SystemClock
from justkernel.shared.errors import InvalidClockError


# ---- fake clock -------------------------------------------------------------
def test_fake_clock_set_and_advance() -> None:
    clock = FakeClock(1000)

    assert clock.now_ms() == 1000
    assert clock.advance(500) == 1500
    assert clock.now_ms() == 1500

    clock.set(42)
    assert clock.now_ms() == 42


def test_fake_clock_rejects_negative_time() -> None:
    with pytest.raises(InvalidClockError):
        FakeClock(-1)

    clock = FakeClock(0)
    with pytest.raises(InvalidClockError):
        clock.advance(-1)
    with pytest.raises(InvalidClockError):
        clock.set(-1)


# ---- system clock -----------------------------------------------------------
def test_system_clock_returns_integer_milliseconds() -> None:
    assert isinstance(SystemClock().now_ms(), int)

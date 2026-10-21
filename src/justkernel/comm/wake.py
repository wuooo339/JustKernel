"""Wake scheduling policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from justkernel.shared.digest import Digest
from justkernel.shared.json import digest_json
from justkernel.testing.policy import PolicyError


# ---- WakePolicy -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WakePolicy:
    wake_debounce_ms: int = 500
    summary_interval_s: int = 30
    wait_deadline_s: int = 300
    stalled_timeout_s: int = 60
    max_stalled_wakes: int = 1

    def __post_init__(self) -> None:
        if self.wake_debounce_ms < 0:
            raise PolicyError("wake_debounce_ms must be non-negative")
        for name in ("summary_interval_s", "wait_deadline_s", "stalled_timeout_s"):
            if getattr(self, name) <= 0:
                raise PolicyError(f"{name} must be positive")
        if self.max_stalled_wakes < 1:
            raise PolicyError("max_stalled_wakes must be at least 1")

    def digest(self) -> Digest:
        return digest_json(asdict(self))

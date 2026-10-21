"""Wake scheduling policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum

from justkernel.shared.digest import Digest
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import AgentId, EventId, WakeId
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


# ---- wake records -----------------------------------------------------------
class WakeState(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WakeError(JustKernelError):
    code = ErrorCode.WAKE_INVALID


@dataclass(frozen=True, slots=True)
class WakeRequest:
    id: WakeId
    agent_id: AgentId
    reason: str
    event_ids: tuple[EventId, ...]
    expected_agent_version: int
    not_before: int
    state: WakeState = WakeState.PENDING

    def __post_init__(self) -> None:
        if not self.reason:
            raise WakeError("wake reason must be non-empty")
        if self.expected_agent_version < 0:
            raise WakeError("expected agent version must be non-negative")
        if self.not_before < 0:
            raise WakeError("not_before must be non-negative")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise WakeError("wake event ids must be unique")

    def claim(self) -> WakeRequest:
        if self.state is not WakeState.PENDING:
            raise WakeError(f"cannot claim a {self.state} wake")
        return replace(self, state=WakeState.CLAIMED)

    def complete(self) -> WakeRequest:
        if self.state is not WakeState.CLAIMED:
            raise WakeError(f"cannot complete a {self.state} wake")
        return replace(self, state=WakeState.COMPLETED)

    def fail(self) -> WakeRequest:
        if self.state is not WakeState.CLAIMED:
            raise WakeError(f"cannot fail a {self.state} wake")
        return replace(self, state=WakeState.FAILED)


@dataclass(frozen=True, slots=True)
class WakeWait:
    agent_id: AgentId
    reason: str
    event_ids: tuple[EventId, ...]
    deadline_ms: int
    created_at: int

    def __post_init__(self) -> None:
        if not self.reason:
            raise WakeError("wait reason must be non-empty")
        if self.deadline_ms <= self.created_at:
            raise WakeError("wait deadline must be in the future")
        if self.created_at < 0:
            raise WakeError("wait creation time must be non-negative")
        if len(set(self.event_ids)) != len(self.event_ids):
            raise WakeError("wait event ids must be unique")

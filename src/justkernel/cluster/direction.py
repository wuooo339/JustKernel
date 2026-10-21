"""Direction aggregate and its lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass, field

from justkernel.cluster.errors import DirectionError
from justkernel.cluster.state import DirectionState
from justkernel.shared.ids import AgentId, ClusterId, DirectionId

TERMINAL_STATES = frozenset({DirectionState.COMPLETED, DirectionState.ABANDONED})


# ---- Direction --------------------------------------------------------------
@dataclass(slots=True)
class Direction:
    id: DirectionId
    cluster_id: ClusterId
    mentor_id: AgentId
    objective: str
    created_at: int
    constraints: tuple[str, ...] = field(default_factory=tuple)
    state: DirectionState = DirectionState.PROPOSED
    summary: str | None = None
    closed_at: int | None = None
    close_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.objective:
            raise DirectionError("objective must be non-empty")
        if any(not constraint for constraint in self.constraints):
            raise DirectionError("constraints must not contain empty values")
        if self.created_at < 0:
            raise DirectionError("created_at must be non-negative")
        if self.summary is not None and not self.summary:
            raise DirectionError("summary must be non-empty")
        terminal = self.state in TERMINAL_STATES
        if terminal != (self.closed_at is not None):
            raise DirectionError("closed_at must be set exactly for terminal states")
        if terminal != (self.close_reason is not None):
            raise DirectionError("close_reason must be set exactly for terminal states")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise DirectionError("closed_at must not precede created_at")

    # ---- validation helpers -------------------------------------------------
    def _require_open(self) -> None:
        if self.state in TERMINAL_STATES:
            raise DirectionError(f"direction is terminal: {self.state}")

    def _require_state(self, *allowed: DirectionState) -> None:
        if self.state not in allowed:
            raise DirectionError(f"cannot transition from {self.state}")

    def _close(self, state: DirectionState, reason: str, now_ms: int) -> None:
        if not reason:
            raise DirectionError("close reason must be non-empty")
        if now_ms < self.created_at:
            raise DirectionError("event time must not precede created_at")
        self.state = state
        self.close_reason = reason
        self.closed_at = now_ms

    # ---- commands -----------------------------------------------------------
    def activate(self) -> None:
        self._require_state(DirectionState.PROPOSED)
        self.state = DirectionState.ACTIVE

    def pause(self) -> None:
        self._require_state(DirectionState.ACTIVE)
        self.state = DirectionState.PAUSED

    def resume(self) -> None:
        self._require_state(DirectionState.PAUSED)
        self.state = DirectionState.ACTIVE

    def set_summary(self, summary: str) -> None:
        self._require_open()
        if not summary:
            raise DirectionError("summary must be non-empty")
        self.summary = summary

    def complete(self, reason: str, now_ms: int) -> None:
        self._require_state(DirectionState.ACTIVE, DirectionState.PAUSED)
        self._close(DirectionState.COMPLETED, reason, now_ms)

    def abandon(self, reason: str, now_ms: int) -> None:
        self._require_state(
            DirectionState.PROPOSED,
            DirectionState.ACTIVE,
            DirectionState.PAUSED,
        )
        self._close(DirectionState.ABANDONED, reason, now_ms)

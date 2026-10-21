"""Agent instance aggregate and lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.errors import AgentError
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import WORKER_ROLES, AgentState, Role
from justkernel.shared.ids import AgentId, ClusterId, TaskId

CLOSED_STATE = AgentState.CLOSED


# ---- AgentInstance ----------------------------------------------------------
@dataclass(slots=True)
class AgentInstance:
    id: AgentId
    cluster_id: ClusterId
    role: Role
    mentor_id: AgentId | None
    model_profile: str
    skills: tuple[SkillRef, ...]
    created_at: int
    state: AgentState = AgentState.CREATED
    session_id: str | None = None
    checkpoint_ref: str | None = None
    current_task_id: TaskId | None = None
    closed_at: int | None = None

    def __post_init__(self) -> None:
        is_worker = self.role in WORKER_ROLES
        if is_worker and self.mentor_id is None:
            raise AgentError("worker requires exactly one mentor")
        if not is_worker and self.mentor_id is not None:
            raise AgentError("non-worker must not have a mentor")
        if not self.model_profile:
            raise AgentError("model_profile must be non-empty")
        if self.created_at < 0:
            raise AgentError("created_at must be non-negative")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise AgentError("closed_at must not precede created_at")
        if self.state is CLOSED_STATE:
            if self.closed_at is None:
                raise AgentError("closed agent requires closed_at")
        elif self.closed_at is not None:
            raise AgentError("only closed agents carry closed_at")
        if self.current_task_id is not None and self.state is not AgentState.RUNNING:
            raise AgentError("current_task_id is only valid while running")
        if self.session_id is not None and not self.session_id:
            raise AgentError("session_id must be non-empty")
        if self.checkpoint_ref is not None and not self.checkpoint_ref:
            raise AgentError("checkpoint_ref must be non-empty")

    # ---- properties ---------------------------------------------------------
    @property
    def is_worker(self) -> bool:
        return self.role in WORKER_ROLES

    @property
    def is_closed(self) -> bool:
        return self.state is CLOSED_STATE

    # ---- guards -------------------------------------------------------------
    def _require_state(self, *allowed: AgentState) -> None:
        if self.state not in allowed:
            raise AgentError(f"cannot transition from {self.state}")

    def _require_open(self) -> None:
        if self.state is CLOSED_STATE:
            raise AgentError("agent is closed")

    def _require_time(self, now_ms: int) -> None:
        if now_ms < self.created_at:
            raise AgentError("event time must not precede created_at")

    # ---- lifecycle commands -------------------------------------------------
    def initialize(self) -> None:
        self._require_state(AgentState.CREATED)
        self.state = AgentState.IDLE

    def start_turn(self) -> None:
        self._require_state(AgentState.IDLE)
        self.state = AgentState.RUNNING

    def finish_turn(self) -> None:
        self._require_state(AgentState.RUNNING)
        self.current_task_id = None
        self.state = AgentState.IDLE

    def start_task(self, task_id: TaskId) -> None:
        self._require_state(AgentState.IDLE)
        self.current_task_id = task_id
        self.state = AgentState.RUNNING

    def complete_task(self) -> None:
        self._require_state(AgentState.RUNNING)
        if self.current_task_id is None:
            raise AgentError("no active task to complete")
        self.current_task_id = None
        self.state = AgentState.IDLE

    def interrupt(self) -> None:
        self._require_state(AgentState.RUNNING)
        self.current_task_id = None
        self.state = AgentState.INTERRUPTED

    def resume(self, session_id: str) -> None:
        self._require_state(AgentState.INTERRUPTED)
        if not session_id:
            raise AgentError("resume requires a new session_id")
        self.session_id = session_id
        self.state = AgentState.IDLE

    def fail(self) -> None:
        self._require_state(AgentState.RUNNING)
        self.current_task_id = None
        self.state = AgentState.FAILED

    def close(self, now_ms: int) -> None:
        self._require_open()
        self._require_state(AgentState.IDLE, AgentState.INTERRUPTED, AgentState.FAILED)
        self._require_time(now_ms)
        self.current_task_id = None
        self.closed_at = now_ms
        self.state = CLOSED_STATE

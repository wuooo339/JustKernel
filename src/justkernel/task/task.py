"""Task aggregate and its lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.skills import SkillRef
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    TaskId,
)
from justkernel.task.errors import TaskError
from justkernel.task.state import TERMINAL_TASK_STATES, TaskKind, TaskState


# ---- Task -------------------------------------------------------------------
@dataclass(slots=True)
class Task:
    id: TaskId
    cluster_id: ClusterId
    mentor_id: AgentId
    worker_id: AgentId
    kind: TaskKind
    direction_id: DirectionId
    operator_spec_ref: OperatorRef
    context_ref: str
    context_digest: Digest
    budget_ref: str
    objective: str
    created_at: int
    candidate_id: CandidateId | None = None
    skill_ref: SkillRef | None = None
    retry_of_task_id: TaskId | None = None
    constraints: tuple[str, ...] = ()
    state: TaskState = TaskState.ASSIGNED
    result_ref: str | None = None
    finished_at: int | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        self._check_kind_fields()
        for name in ("context_ref", "budget_ref", "objective"):
            if not getattr(self, name):
                raise TaskError(f"{name} must be non-empty")
        if any(not constraint for constraint in self.constraints):
            raise TaskError("constraints must not contain empty values")
        if self.created_at < 0:
            raise TaskError("created_at must be non-negative")
        if self.retry_of_task_id == self.id:
            raise TaskError("retry task must use a new TaskId")
        self._check_terminal_fields()

    # ---- validation helpers -------------------------------------------------
    def _check_kind_fields(self) -> None:
        if self.kind is TaskKind.GENERATE:
            if self.candidate_id is not None or self.skill_ref is not None:
                raise TaskError("GENERATE must not have candidate or skill")
        elif self.kind is TaskKind.OPTIMIZE:
            if self.candidate_id is None or self.skill_ref is not None:
                raise TaskError("OPTIMIZE requires a candidate and no skill")
        elif self.kind in (TaskKind.TEST, TaskKind.PROFILE):
            if self.candidate_id is None or self.skill_ref is None:
                raise TaskError(f"{self.kind} requires candidate and skill")
        else:
            raise TaskError(f"unknown task kind {self.kind!r}")

    def _check_terminal_fields(self) -> None:
        terminal = self.state in TERMINAL_TASK_STATES
        if terminal != (self.finished_at is not None):
            raise TaskError("finished_at must be set exactly for terminal states")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise TaskError("finished_at must not precede created_at")
        if self.result_ref is not None and not self.result_ref:
            raise TaskError("result_ref must be non-empty")
        if not terminal and self.result_ref is not None:
            raise TaskError("non-terminal task must not have result_ref")
        if self.state is TaskState.SUCCEEDED:
            if self.result_ref is None:
                raise TaskError("SUCCEEDED requires result_ref")
            if self.terminal_reason is not None:
                raise TaskError("SUCCEEDED must not have terminal_reason")
        elif self.state in (TaskState.FAILED, TaskState.CANCELLED, TaskState.INTERRUPTED):
            if not self.terminal_reason:
                raise TaskError("failure/cancel/interrupt requires a reason")
        elif self.terminal_reason is not None:
            raise TaskError("non-terminal task must not have terminal_reason")

    # ---- guards -------------------------------------------------------------
    def _require_state(self, *allowed: TaskState) -> None:
        if self.state not in allowed:
            raise TaskError(f"cannot transition from {self.state}")

    def _require_time(self, now_ms: int) -> None:
        if now_ms < self.created_at:
            raise TaskError("event time must not precede created_at")

    def _finish(
        self,
        state: TaskState,
        reason: str | None,
        now_ms: int,
        result_ref: str | None = None,
    ) -> None:
        self._require_time(now_ms)
        self.state = state
        self.terminal_reason = reason
        self.result_ref = result_ref
        self.finished_at = now_ms

    # ---- commands -----------------------------------------------------------
    def start(self) -> None:
        self._require_state(TaskState.ASSIGNED)
        self.state = TaskState.RUNNING

    def succeed(self, result_ref: str, now_ms: int) -> None:
        self._require_state(TaskState.RUNNING)
        if not result_ref:
            raise TaskError("result_ref must be non-empty")
        self._finish(TaskState.SUCCEEDED, None, now_ms, result_ref)

    def fail(self, reason: str, now_ms: int) -> None:
        self._require_state(TaskState.RUNNING)
        if not reason:
            raise TaskError("failure reason must be non-empty")
        self._finish(TaskState.FAILED, reason, now_ms)

    def cancel(self, reason: str, now_ms: int) -> None:
        self._require_state(TaskState.ASSIGNED, TaskState.RUNNING)
        if not reason:
            raise TaskError("cancel reason must be non-empty")
        self._finish(TaskState.CANCELLED, reason, now_ms)

    def interrupt(self, reason: str, now_ms: int) -> None:
        self._require_state(TaskState.ASSIGNED, TaskState.RUNNING)
        if not reason:
            raise TaskError("interrupt reason must be non-empty")
        self._finish(TaskState.INTERRUPTED, reason, now_ms)

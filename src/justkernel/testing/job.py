"""Tool job state and immutable job record."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from justkernel.shared.digest import Digest
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import CandidateId, TaskId


# ---- ToolJobState -----------------------------------------------------------
class ToolJobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


TERMINAL_JOB_STATES = frozenset(
    {
        ToolJobState.SUCCEEDED,
        ToolJobState.FAILED,
        ToolJobState.CANCELLED,
        ToolJobState.INTERRUPTED,
    }
)


# ---- ToolJobError -----------------------------------------------------------
class ToolJobError(JustKernelError):
    code = ErrorCode.INVALID_TOOL_JOB


# ---- ToolJob ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolJob:
    id: str
    task_id: TaskId
    candidate_id: CandidateId
    request_digest: Digest
    state: ToolJobState
    created_at: int
    started_at: int | None = None
    finished_at: int | None = None
    queue_expires_at: int | None = None
    execution_timeout_s: int | None = None
    queue_position: int | None = None
    record_id: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ToolJobError("tool job id must be non-empty")
        if self.created_at < 0:
            raise ToolJobError("created_at must be non-negative")
        for name in ("started_at", "finished_at"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ToolJobError(f"{name} must be non-negative")
        if self.queue_expires_at is not None and self.queue_expires_at <= self.created_at:
            raise ToolJobError("queue_expires_at must be after created_at")
        if self.execution_timeout_s is not None and self.execution_timeout_s <= 0:
            raise ToolJobError("execution_timeout_s must be positive")
        if self.queue_position is not None and self.queue_position < 1:
            raise ToolJobError("queue_position must be positive")
        if self.record_id is not None and not self.record_id:
            raise ToolJobError("record_id must be non-empty")
        if self.error is not None and not self.error:
            raise ToolJobError("error must be non-empty")

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_JOB_STATES

    def start(self, now_ms: int) -> ToolJob:
        if self.state is not ToolJobState.QUEUED:
            raise ToolJobError(f"cannot start a {self.state} job")
        self._check_time(now_ms)
        if self.queue_expires_at is not None and now_ms >= self.queue_expires_at:
            raise ToolJobError("queue deadline reached")
        return replace(
            self,
            state=ToolJobState.RUNNING,
            started_at=now_ms,
            queue_position=None,
        )

    def timeout(self, now_ms: int) -> ToolJob:
        if self.state is ToolJobState.QUEUED:
            if self.queue_expires_at is None or now_ms < self.queue_expires_at:
                raise ToolJobError("queue deadline has not been reached")
            return self._finished(ToolJobState.FAILED, now_ms, "queue timeout")
        if self.state is ToolJobState.RUNNING:
            deadline = self._execution_deadline()
            if now_ms < deadline:
                raise ToolJobError("execution deadline has not been reached")
            return self._finished(ToolJobState.FAILED, now_ms, "execution timeout")
        raise ToolJobError(f"cannot time out a {self.state} job")

    def cancel(self, reason: str, now_ms: int) -> ToolJob:
        self._require_active(reason, now_ms)
        return self._finished(ToolJobState.CANCELLED, now_ms, reason)

    def interrupt(self, reason: str, now_ms: int) -> ToolJob:
        self._require_active(reason, now_ms)
        return self._finished(ToolJobState.INTERRUPTED, now_ms, reason)

    def fail(self, error: str, now_ms: int) -> ToolJob:
        if self.state is not ToolJobState.RUNNING:
            raise ToolJobError(f"cannot fail a {self.state} job")
        self._check_time(now_ms)
        if not error:
            raise ToolJobError("failure reason must be non-empty")
        return self._finished(ToolJobState.FAILED, now_ms, error)

    def succeed(self, record_id: str, now_ms: int) -> ToolJob:
        if self.state is not ToolJobState.RUNNING:
            raise ToolJobError(f"cannot succeed a {self.state} job")
        self._check_time(now_ms)
        if not record_id:
            raise ToolJobError("record id must be non-empty")
        return self._finished(ToolJobState.SUCCEEDED, now_ms, None, record_id)

    def _require_active(self, reason: str, now_ms: int) -> None:
        if self.is_terminal:
            raise ToolJobError(f"job is already terminal: {self.state}")
        if not reason:
            raise ToolJobError("reason must be non-empty")
        self._check_time(now_ms)

    def _execution_deadline(self) -> int:
        if self.started_at is None or self.execution_timeout_s is None:
            raise ToolJobError("running job has no execution deadline")
        return self.started_at + self.execution_timeout_s

    def _finished(
        self,
        state: ToolJobState,
        now_ms: int,
        error: str | None,
        record_id: str | None = None,
    ) -> ToolJob:
        return replace(
            self,
            state=state,
            finished_at=now_ms,
            error=error,
            record_id=record_id,
            queue_position=None,
        )

    def _check_time(self, now_ms: int) -> None:
        if now_ms < self.created_at:
            raise ToolJobError("job time must not precede created_at")


# ---- ToolJobView ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolJobView:
    job_id: str
    task_id: TaskId
    state: ToolJobState
    record_id: str | None = None
    error: str | None = None
    queue_position: int | None = None

    @classmethod
    def from_job(cls, job: ToolJob) -> ToolJobView:
        return cls(
            job_id=job.id,
            task_id=job.task_id,
            state=job.state,
            record_id=job.record_id,
            error=job.error,
            queue_position=job.queue_position,
        )

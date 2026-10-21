"""Tool job state and immutable job record."""

from __future__ import annotations

from dataclasses import dataclass
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
    record_id: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ToolJobError("tool job id must be non-empty")
        if self.created_at < 0:
            raise ToolJobError("created_at must be non-negative")
        if self.record_id is not None and not self.record_id:
            raise ToolJobError("record_id must be non-empty")
        if self.error is not None and not self.error:
            raise ToolJobError("error must be non-empty")

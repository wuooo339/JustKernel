"""Task lifecycle errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- TaskError --------------------------------------------------------------
class TaskError(JustKernelError):
    code = ErrorCode.INVALID_TASK_TRANSITION

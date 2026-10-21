"""Application-level access errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- ToolAccessError --------------------------------------------------------
class ToolAccessError(JustKernelError):
    code = ErrorCode.TOOL_DENIED


# ---- ToolNotFoundError ------------------------------------------------------
class ToolNotFoundError(JustKernelError):
    code = ErrorCode.TOOL_NOT_FOUND

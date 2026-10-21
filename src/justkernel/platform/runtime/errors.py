"""Runtime and checkpoint errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- AgentRuntimeError ------------------------------------------------------
class AgentRuntimeError(JustKernelError):
    code = ErrorCode.RUNTIME_ERROR


# ---- RuntimeLimitError ------------------------------------------------------
class RuntimeLimitError(AgentRuntimeError):
    code = ErrorCode.RUNTIME_LIMIT


# ---- RuntimeStateError ------------------------------------------------------
class RuntimeStateError(AgentRuntimeError):
    code = ErrorCode.RUNTIME_STATE


# ---- CheckpointError --------------------------------------------------------
class CheckpointError(AgentRuntimeError):
    code = ErrorCode.CHECKPOINT_INVALID

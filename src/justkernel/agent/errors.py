"""Agent lifecycle errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- AgentError -------------------------------------------------------------
class AgentError(JustKernelError):
    code = ErrorCode.INVALID_AGENT_TRANSITION

"""Agent lifecycle errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- AgentError -------------------------------------------------------------
class AgentError(JustKernelError):
    code = "invalid_agent_transition"

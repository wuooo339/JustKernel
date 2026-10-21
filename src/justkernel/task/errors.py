"""Task lifecycle errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- TaskError --------------------------------------------------------------
class TaskError(JustKernelError):
    code = "invalid_task_transition"

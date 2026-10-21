"""Persistence errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- ConcurrencyError -------------------------------------------------------
class ConcurrencyError(JustKernelError):
    code = ErrorCode.CONCURRENCY_CONFLICT

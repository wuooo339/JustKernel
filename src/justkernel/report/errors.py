"""Exploration report errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- ReportError ------------------------------------------------------------
class ReportError(JustKernelError):
    code = ErrorCode.INVALID_REPORT

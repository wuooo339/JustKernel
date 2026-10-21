"""Exploration report errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- ReportError ------------------------------------------------------------
class ReportError(JustKernelError):
    code = "invalid_report"

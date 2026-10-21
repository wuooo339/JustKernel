"""Candidate and best-selection errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- CandidateError ---------------------------------------------------------
class CandidateError(JustKernelError):
    code = ErrorCode.INVALID_CANDIDATE


# ---- BestSelectionError -----------------------------------------------------
class BestSelectionError(JustKernelError):
    code = ErrorCode.INVALID_BEST_SELECTION

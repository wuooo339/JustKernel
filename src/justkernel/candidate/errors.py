"""Candidate and best-selection errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- CandidateError ---------------------------------------------------------
class CandidateError(JustKernelError):
    code = "invalid_candidate"


# ---- BestSelectionError -----------------------------------------------------
class BestSelectionError(JustKernelError):
    code = "invalid_best_selection"

"""Testing and lease errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- TestRecordError --------------------------------------------------------
class TestRecordError(JustKernelError):
    code = "invalid_test_record"


# ---- LeaseError -------------------------------------------------------------
class LeaseError(JustKernelError):
    code = "invalid_lease_transition"

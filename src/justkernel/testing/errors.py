"""Testing and lease errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- TestRecordError --------------------------------------------------------
class TestRecordError(JustKernelError):
    code = ErrorCode.INVALID_TEST_RECORD


# ---- LeaseError -------------------------------------------------------------
class LeaseError(JustKernelError):
    code = ErrorCode.INVALID_LEASE_TRANSITION

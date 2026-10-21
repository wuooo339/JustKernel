"""Stable shared error types."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode


# ---- JustKernelError --------------------------------------------------------
class JustKernelError(Exception):
    """Base error with a stable machine-readable code."""

    code = ErrorCode.JUSTKERNEL_ERROR

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"{self.code}: {message}")


# ---- validation errors ------------------------------------------------------
class InvalidIdError(JustKernelError):
    code = ErrorCode.INVALID_ID


class InvalidDigestError(JustKernelError):
    code = ErrorCode.INVALID_DIGEST


class InvalidJsonError(JustKernelError):
    code = ErrorCode.INVALID_JSON


class InvalidClockError(JustKernelError):
    code = ErrorCode.INVALID_CLOCK


class InvalidPrincipalError(JustKernelError):
    code = ErrorCode.INVALID_PRINCIPAL


class InvalidProjectPathError(JustKernelError):
    code = ErrorCode.INVALID_PROJECT_PATH

"""Stable shared error types."""

from __future__ import annotations


# ---- JustKernelError --------------------------------------------------------
class JustKernelError(Exception):
    """Base error with a stable machine-readable code."""

    code = "justkernel_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"{self.code}: {message}")


# ---- validation errors ------------------------------------------------------
class InvalidIdError(JustKernelError):
    code = "invalid_id"


class InvalidDigestError(JustKernelError):
    code = "invalid_digest"


class InvalidJsonError(JustKernelError):
    code = "invalid_json"


class InvalidClockError(JustKernelError):
    code = "invalid_clock"


class InvalidPrincipalError(JustKernelError):
    code = "invalid_principal"


class InvalidProjectPathError(JustKernelError):
    code = "invalid_project_path"

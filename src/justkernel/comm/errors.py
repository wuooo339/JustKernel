"""Communication and ACL errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- ChannelError -----------------------------------------------------------
class ChannelError(JustKernelError):
    code = ErrorCode.INVALID_CHANNEL


# ---- AccessDeniedError ------------------------------------------------------
class AccessDeniedError(JustKernelError):
    code = ErrorCode.ACL_DENIED


# ---- MessageError -----------------------------------------------------------
class MessageError(JustKernelError):
    code = ErrorCode.INVALID_MESSAGE

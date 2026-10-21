"""Communication and ACL errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- ChannelError -----------------------------------------------------------
class ChannelError(JustKernelError):
    code = "invalid_channel"


# ---- AccessDeniedError ------------------------------------------------------
class AccessDeniedError(JustKernelError):
    code = "acl.denied"


# ---- MessageError -----------------------------------------------------------
class MessageError(JustKernelError):
    code = "invalid_message"

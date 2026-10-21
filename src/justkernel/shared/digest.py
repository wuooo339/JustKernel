"""Content digests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Self

from justkernel.shared.errors import InvalidDigestError

DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


# ---- Digest -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Digest:
    """SHA-256 digest rendered as 64 lowercase hexadecimal characters."""

    value: str

    def __post_init__(self) -> None:
        if not DIGEST_PATTERN.fullmatch(self.value):
            raise InvalidDigestError(f"expected 64 lowercase hex characters, got {self.value!r}")

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        return cls(sha256(data).hexdigest())

    @classmethod
    def from_text(cls, text: str) -> Self:
        return cls.from_bytes(text.encode("utf-8"))

    def __str__(self) -> str:
        return self.value

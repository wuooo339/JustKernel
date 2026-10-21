"""Canonical JSON helpers for idempotency keys and digests."""

from __future__ import annotations

import json

from justkernel.shared.digest import Digest
from justkernel.shared.errors import InvalidJsonError


# ---- canonical encoding -----------------------------------------------------
def canonical_json(value: object) -> str:
    """Encode UTF-8 JSON with sorted keys and compact separators."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise InvalidJsonError(str(error)) from error


def canonical_bytes(value: object) -> bytes:
    """Encode a value as canonical UTF-8 bytes."""
    return canonical_json(value).encode("utf-8")


def digest_json(value: object) -> Digest:
    """Digest a value using its canonical JSON encoding."""
    return Digest.from_bytes(canonical_bytes(value))

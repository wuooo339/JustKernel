from __future__ import annotations

from hashlib import sha256

import pytest

from justkernel.shared.digest import Digest
from justkernel.shared.errors import InvalidDigestError


# ---- construction -----------------------------------------------------------
def test_digest_from_bytes_and_text() -> None:
    expected = sha256(b"abc").hexdigest()

    assert Digest.from_bytes(b"abc").value == expected
    assert Digest.from_text("abc") == Digest.from_bytes(b"abc")
    assert str(Digest.from_text("abc")) == expected


# ---- validation -------------------------------------------------------------
def test_digest_rejects_invalid_values() -> None:
    for value in ("", "A" * 64, "a" * 63, "g" * 64):
        with pytest.raises(InvalidDigestError):
            Digest(value)

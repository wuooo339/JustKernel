from __future__ import annotations

import math

import pytest

from justkernel.shared.errors import InvalidJsonError
from justkernel.shared.json import canonical_bytes, canonical_json, digest_json


# ---- canonical output -------------------------------------------------------
def test_canonical_json_sorts_keys_and_keeps_utf8() -> None:
    value = {"b": 1, "a": "中"}

    assert canonical_json(value) == '{"a":"中","b":1}'
    assert canonical_bytes(value) == '{"a":"中","b":1}'.encode()


def test_canonical_json_is_stable_for_equivalent_objects() -> None:
    assert canonical_json({"a": 1, "b": 2}) == canonical_json({"b": 2, "a": 1})


# ---- invalid numbers --------------------------------------------------------
def test_canonical_json_rejects_nan_and_infinity() -> None:
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(InvalidJsonError):
            canonical_json({"value": value})


# ---- digest -----------------------------------------------------------------
def test_digest_json_depends_on_content() -> None:
    assert digest_json({"a": 1}) == digest_json({"a": 1})
    assert digest_json({"a": 1}) != digest_json({"a": 2})

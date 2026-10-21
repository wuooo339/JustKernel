from __future__ import annotations

import re
from uuid import uuid4

import pytest

from justkernel.shared.errors import InvalidIdError
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    LeaseId,
    MessageId,
    TaskId,
)
from justkernel.shared.ids import TestRecordId as RecordId

ID_TYPES = (
    ClusterId,
    AgentId,
    DirectionId,
    TaskId,
    CandidateId,
    RecordId,
    MessageId,
    LeaseId,
)
HEX32 = re.compile(r"^[0-9a-f]{32}$")


# ---- generation -------------------------------------------------------------
def test_generate_returns_32_lowercase_hex() -> None:
    for id_type in ID_TYPES:
        value = id_type.generate()

        assert isinstance(value, id_type)
        assert HEX32.fullmatch(value.value)
        assert str(value) == value.value


# ---- validation -------------------------------------------------------------
def test_rejects_invalid_values() -> None:
    invalid = ["", "A" * 32, "a" * 31, "g" * 32, str(uuid4())]

    for id_type in ID_TYPES:
        for value in invalid:
            with pytest.raises(InvalidIdError):
                id_type(value)


def test_id_types_are_not_equal() -> None:
    value = "a" * 32

    assert ClusterId(value) != AgentId(value)
    assert ClusterId(value) == ClusterId(value)

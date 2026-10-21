"""Validated UUID4 identifiers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Self
from uuid import uuid4

from justkernel.shared.errors import InvalidIdError

ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


# ---- Identifier -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Identifier:
    """Base class for 32-character lowercase hexadecimal UUID4 identifiers."""

    value: str

    def __post_init__(self) -> None:
        if not ID_PATTERN.fullmatch(self.value):
            raise InvalidIdError(f"expected 32 lowercase hex characters, got {self.value!r}")

    @classmethod
    def generate(cls) -> Self:
        return cls(uuid4().hex)

    def __str__(self) -> str:
        return self.value


# ---- identifier types -------------------------------------------------------
class ClusterId(Identifier):
    """Identifier of a single-operator cluster."""


class AgentId(Identifier):
    """Identifier of an agent instance."""


class DirectionId(Identifier):
    """Identifier of a mentor direction."""


class TaskId(Identifier):
    """Identifier of a mentor-to-worker task."""


class CandidateId(Identifier):
    """Identifier of an immutable candidate version."""


class TestRecordId(Identifier):
    """Identifier of a TestRecord."""


class MessageId(Identifier):
    """Identifier of an idempotent message."""


class LeaseId(Identifier):
    """Identifier of a hardware lease."""

"""Typed communication channels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from justkernel.comm.errors import ChannelError
from justkernel.shared.errors import InvalidIdError
from justkernel.shared.ids import AgentId


# ---- ChannelKind ------------------------------------------------------------
class ChannelKind(StrEnum):
    MENTOR_BOARD = "MENTOR_BOARD"
    CONSULTANT_BOARD = "CONSULTANT_BOARD"
    WORKER = "WORKER"
    HARDWARE = "HARDWARE"
    CONTROL = "CONTROL"
    EXTERNAL = "EXTERNAL"


# ---- Channel ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Channel:
    kind: ChannelKind
    mentor_id: AgentId | None = None
    worker_id: AgentId | None = None

    def __post_init__(self) -> None:
        if self.kind is ChannelKind.WORKER:
            if self.mentor_id is None or self.worker_id is None:
                raise ChannelError("worker channel requires mentor and worker ids")
        elif self.mentor_id is not None or self.worker_id is not None:
            raise ChannelError("only worker channels carry agent ids")

    @classmethod
    def mentor_board(cls) -> Self:
        return cls(ChannelKind.MENTOR_BOARD)

    @classmethod
    def consultant_board(cls) -> Self:
        return cls(ChannelKind.CONSULTANT_BOARD)

    @classmethod
    def hardware(cls) -> Self:
        return cls(ChannelKind.HARDWARE)

    @classmethod
    def control(cls) -> Self:
        return cls(ChannelKind.CONTROL)

    @classmethod
    def external(cls) -> Self:
        return cls(ChannelKind.EXTERNAL)

    @classmethod
    def worker(cls, mentor_id: AgentId, worker_id: AgentId) -> Self:
        return cls(ChannelKind.WORKER, mentor_id=mentor_id, worker_id=worker_id)

    @classmethod
    def parse(cls, name: str) -> Self:
        if name == "mentor_board":
            return cls.mentor_board()
        if name == "consultant_board":
            return cls.consultant_board()
        if name == "hardware":
            return cls.hardware()
        if name == "control":
            return cls.control()
        if name == "external":
            return cls.external()
        if name.startswith("worker:"):
            parts = name.split(":")
            if len(parts) != 3:
                raise ChannelError(f"invalid worker channel {name!r}")
            try:
                return cls.worker(AgentId(parts[1]), AgentId(parts[2]))
            except InvalidIdError as error:
                raise ChannelError(f"invalid worker channel {name!r}") from error
        raise ChannelError(f"unknown channel {name!r}")

    @property
    def name(self) -> str:
        if self.kind is ChannelKind.WORKER:
            assert self.mentor_id is not None and self.worker_id is not None
            return f"worker:{self.mentor_id}:{self.worker_id}"
        return self.kind.value.lower()

    def __str__(self) -> str:
        return self.name

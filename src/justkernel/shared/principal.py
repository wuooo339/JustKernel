"""Validated principals for messages, mentions, and audit records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

from justkernel.shared.errors import InvalidIdError, InvalidPrincipalError
from justkernel.shared.ids import AgentId

PrincipalKind = Literal["agent", "human", "system"]


# ---- Principal --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated actor: one agent, a human, or the system."""

    kind: PrincipalKind
    agent_id: AgentId | None = None

    def __post_init__(self) -> None:
        kind_value: str = self.kind
        if kind_value not in ("agent", "human", "system"):
            raise InvalidPrincipalError(f"unknown principal kind {self.kind!r}")
        if self.kind == "agent" and self.agent_id is None:
            raise InvalidPrincipalError("agent principal requires an agent id")
        if self.kind != "agent" and self.agent_id is not None:
            raise InvalidPrincipalError("only agent principals carry an agent id")

    @classmethod
    def agent(cls, agent_id: AgentId) -> Self:
        return cls("agent", agent_id)

    @classmethod
    def human(cls) -> Self:
        return cls("human")

    @classmethod
    def system(cls) -> Self:
        return cls("system")

    @classmethod
    def parse(cls, value: str) -> Self:
        if value == "human":
            return cls.human()
        if value == "system":
            return cls.system()
        prefix = "agent:"
        if value.startswith(prefix):
            try:
                return cls.agent(AgentId(value[len(prefix) :]))
            except InvalidIdError as error:
                raise InvalidPrincipalError(str(error)) from error
        raise InvalidPrincipalError(f"invalid principal {value!r}")

    def __str__(self) -> str:
        if self.kind == "agent":
            assert self.agent_id is not None
            return f"agent:{self.agent_id}"
        return self.kind

"""Agent runner contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.shared.ids import AgentId, ClusterId


# ---- AgentRunRequest --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    agent_id: AgentId
    cluster_id: ClusterId
    role: Role
    model_profile: str
    skills: tuple[SkillRef, ...]
    session_id: str
    input: str
    mentor_id: AgentId | None = None
    checkpoint: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if self.checkpoint is not None:
            object.__setattr__(self, "checkpoint", MappingProxyType(dict(self.checkpoint)))


# ---- RunnerResult -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RunnerResult:
    output: str
    checkpoint: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.checkpoint is not None:
            object.__setattr__(self, "checkpoint", MappingProxyType(dict(self.checkpoint)))


# ---- AgentRunner ------------------------------------------------------------
class AgentRunner(Protocol):
    def run(self, request: AgentRunRequest) -> RunnerResult: ...

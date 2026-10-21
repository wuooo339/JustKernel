"""Skill references bound to an agent."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.errors import AgentError
from justkernel.shared.digest import Digest


# ---- SkillRef ---------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SkillRef:
    name: str
    version: str
    source_path: str
    digest: Digest

    def __post_init__(self) -> None:
        for field_name in ("name", "version", "source_path"):
            if not getattr(self, field_name):
                raise AgentError(f"skill {field_name} must be non-empty")

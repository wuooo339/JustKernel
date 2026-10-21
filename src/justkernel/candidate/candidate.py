"""Immutable candidate version."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.candidate.errors import CandidateError
from justkernel.candidate.source import SourceRevision
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    TaskId,
)
from justkernel.shared.principal import Principal


# ---- CandidateVersion -------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CandidateVersion:
    id: CandidateId
    cluster_id: ClusterId
    direction_id: DirectionId
    parent_id: CandidateId | None
    author_agent_id: AgentId | None
    author_principal: Principal
    task_id: TaskId | None
    import_id: str | None
    source: SourceRevision
    diff_artifact: str
    created_at: int

    def __post_init__(self) -> None:
        if (self.task_id is None) == (self.import_id is None):
            raise CandidateError("candidate requires exactly one provenance source")
        if self.task_id is not None:
            if self.author_agent_id is None:
                raise CandidateError("task candidate requires an author agent")
            if (
                self.author_principal.kind != "agent"
                or self.author_principal.agent_id != self.author_agent_id
            ):
                raise CandidateError("task candidate principal must match author")
        else:
            if self.author_agent_id is not None:
                raise CandidateError("import candidate must not have an author agent")
            if self.author_principal.kind != "system":
                raise CandidateError("import candidate principal must be system")
            if not self.import_id:
                raise CandidateError("import candidate requires an import id")
        if self.parent_id == self.id:
            raise CandidateError("candidate cannot parent itself")
        if not self.diff_artifact:
            raise CandidateError("diff_artifact must be non-empty")
        if self.created_at < 0:
            raise CandidateError("created_at must be non-negative")

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

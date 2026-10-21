"""Application service for candidate import and commit."""

from __future__ import annotations

from collections.abc import Mapping

from justkernel.agent.agent import AgentInstance
from justkernel.agent.state import Role
from justkernel.application.ports import (
    AgentRepositoryPort,
    CandidateRepositoryPort,
    IdFactoryPort,
    TaskRepositoryPort,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import CandidateError
from justkernel.candidate.source import SourceRevision
from justkernel.shared.ids import AgentId, CandidateId, ClusterId, DirectionId, TaskId
from justkernel.shared.principal import Principal
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task


# ---- CandidateService -------------------------------------------------------
class CandidateService:
    def __init__(
        self,
        candidates: CandidateRepositoryPort,
        tasks: TaskRepositoryPort,
        agents: AgentRepositoryPort,
        ids: IdFactoryPort,
    ) -> None:
        self.candidates = candidates
        self.tasks = tasks
        self.agents = agents
        self.ids = ids

    def import_candidate(
        self,
        *,
        cluster_id: ClusterId,
        direction_id: DirectionId,
        source_files: Mapping[str, str],
        diff_artifact: str,
        import_id: str,
        created_at: int,
    ) -> CandidateVersion:
        source = SourceRevision.from_files(source_files)
        candidate = CandidateVersion(
            id=self.ids.candidate_id(),
            cluster_id=cluster_id,
            direction_id=direction_id,
            parent_id=None,
            author_agent_id=None,
            author_principal=Principal.system(),
            task_id=None,
            import_id=import_id,
            source=source,
            diff_artifact=diff_artifact,
            created_at=created_at,
        )
        self.candidates.insert(candidate)
        return candidate

    def commit_candidate(
        self,
        *,
        task_id: TaskId,
        author_agent_id: AgentId,
        source_files: Mapping[str, str],
        diff_artifact: str,
        created_at: int,
    ) -> CandidateVersion:
        task, worker = self._commit_source(task_id, author_agent_id)
        candidate = self._new_candidate(task, worker, source_files, diff_artifact, created_at)
        self.candidates.insert(candidate)
        return candidate

    def find_duplicate(self, candidate_id: CandidateId) -> CandidateVersion | None:
        candidate = self.candidates.get(candidate_id)
        matches = [
            other
            for other in self.candidates.list_by_cluster(candidate.cluster_id)
            if other.id != candidate.id and other.source.digest == candidate.source.digest
        ]
        if not matches:
            return None
        earliest = min(
            [candidate, *matches],
            key=lambda item: (item.created_at, item.id.value),
        )
        return None if earliest.id == candidate.id else earliest

    def is_duplicate(self, candidate_id: CandidateId) -> bool:
        return self.find_duplicate(candidate_id) is not None

    def _commit_source(
        self, task_id: TaskId, author_agent_id: AgentId
    ) -> tuple[Task, AgentInstance]:
        task = self.tasks.get(task_id)
        if task.kind not in (TaskKind.GENERATE, TaskKind.OPTIMIZE):
            raise CandidateError("candidate can only be committed by GENERATE/OPTIMIZE")
        if task.state is not TaskState.RUNNING:
            raise CandidateError("candidate task is not running")
        worker = self.agents.get(author_agent_id)
        if worker.id != task.worker_id or worker.role is not Role.OPTIMIZER:
            raise CandidateError("candidate author is not the task optimizer")
        return task, worker

    def _new_candidate(
        self,
        task: Task,
        worker: AgentInstance,
        source_files: Mapping[str, str],
        diff_artifact: str,
        created_at: int,
    ) -> CandidateVersion:
        return CandidateVersion(
            id=self.ids.candidate_id(),
            cluster_id=task.cluster_id,
            direction_id=task.direction_id,
            parent_id=self._parent_id(task),
            author_agent_id=worker.id,
            author_principal=Principal.agent(worker.id),
            task_id=task.id,
            import_id=None,
            source=SourceRevision.from_files(source_files),
            diff_artifact=diff_artifact,
            created_at=created_at,
        )

    def _parent_id(self, task: Task) -> CandidateId | None:
        parent_id = None if task.kind is TaskKind.GENERATE else task.candidate_id
        if task.kind is TaskKind.OPTIMIZE and parent_id is None:
            raise CandidateError("OPTIMIZE requires a base candidate")
        if parent_id is not None:
            try:
                parent = self.candidates.get(parent_id)
            except KeyError as error:
                raise CandidateError("parent candidate does not exist") from error
            if parent.cluster_id != task.cluster_id:
                raise CandidateError("parent candidate belongs to another cluster")
        return parent_id

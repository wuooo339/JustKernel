"""Application service for immutable task contexts and read-only artifact grants."""

from __future__ import annotations

from justkernel.application.ports import (
    ArtifactStorePort,
    CandidateRepositoryPort,
    TaskRepositoryPort,
)
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, TaskId
from justkernel.shared.paths import ProjectPath
from justkernel.task.context import (
    ArtifactGrant,
    CandidateRef,
    EmptyReason,
    FeedbackRef,
    HistoryEntry,
    SharedEvidence,
    TaskBudget,
    TaskContext,
    TaskContextError,
)
from justkernel.task.state import TaskKind
from justkernel.task.task import Task


# ---- TaskContextService -----------------------------------------------------
class TaskContextService:
    def __init__(self, tasks: TaskRepositoryPort, candidates: CandidateRepositoryPort) -> None:
        self.tasks = tasks
        self.candidates = candidates

    def create_context(
        self,
        *,
        task_id: TaskId,
        mentor_id: AgentId,
        base_candidate_ref: CandidateRef | None,
        objective: str,
        acceptance: tuple[str, ...],
        feedback: tuple[FeedbackRef, ...],
        history: tuple[HistoryEntry, ...],
        shared_evidence: tuple[SharedEvidence, ...],
        resource_grants: tuple[ArtifactGrant, ...],
        budget: TaskBudget,
        empty_reasons: tuple[EmptyReason, ...] = (),
        now_ms: int = 0,
    ) -> TaskContext:
        task = self.tasks.get(task_id)
        if task.mentor_id != mentor_id:
            raise TaskContextError("only the task mentor can create its context")
        if now_ms < 0:
            raise TaskContextError("context time must be non-negative")
        self._check_base(task, base_candidate_ref)
        self._check_grants(task, resource_grants, now_ms)
        return TaskContext(
            task_id=task.id,
            operator_spec_ref=task.operator_spec_ref,
            base_candidate_ref=base_candidate_ref,
            objective=objective,
            acceptance=acceptance,
            feedback=feedback,
            history=history,
            shared_evidence=shared_evidence,
            resource_grants=resource_grants,
            budget=budget,
            empty_reasons=empty_reasons,
        )

    def read_context(
        self,
        task_id: TaskId,
        context: TaskContext,
        caller_agent_id: AgentId,
    ) -> TaskContext:
        task = self.tasks.get(task_id)
        if context.task_id != task.id:
            raise TaskContextError("context does not belong to this task")
        self._require_caller(task, caller_agent_id)
        return context

    def authorize_artifact(
        self,
        context: TaskContext,
        artifact_digest: Digest,
        path: ProjectPath,
        now_ms: int,
    ) -> ArtifactGrant:
        if now_ms < 0:
            raise TaskContextError("authorization time must be non-negative")
        matching = [
            grant for grant in context.resource_grants if grant.artifact_digest == artifact_digest
        ]
        if not matching:
            raise TaskContextError("artifact digest is not granted")
        scope_error = False
        for grant in matching:
            if now_ms >= grant.expires_at_ms:
                scope_error = True
                continue
            if _within_scope(path, grant.readonly_scope):
                return grant
            scope_error = True
        if scope_error:
            raise TaskContextError("artifact grant is expired or outside its scope")
        raise TaskContextError("artifact is not authorized")

    def read_artifact(
        self,
        task_id: TaskId,
        context: TaskContext,
        caller_agent_id: AgentId,
        artifact_digest: Digest,
        path: ProjectPath,
        now_ms: int,
        store: ArtifactStorePort,
    ) -> bytes:
        self.read_context(task_id, context, caller_agent_id)
        self.authorize_artifact(context, artifact_digest, path, now_ms)
        return store.get_bytes(artifact_digest)

    def _check_base(self, task: Task, base: CandidateRef | None) -> None:
        if task.kind is TaskKind.GENERATE:
            if base is not None:
                raise TaskContextError("GENERATE task must not have a base candidate")
            return
        if base is None or base.candidate_id != task.candidate_id:
            raise TaskContextError("base candidate must match the task candidate")
        try:
            candidate = self.candidates.get(base.candidate_id)
        except KeyError as error:
            raise TaskContextError("base candidate does not exist") from error
        if candidate.cluster_id != task.cluster_id:
            raise TaskContextError("base candidate belongs to another cluster")
        if candidate.source.digest != base.source_digest:
            raise TaskContextError("base candidate source digest mismatch")

    def _check_grants(
        self,
        task: Task,
        grants: tuple[ArtifactGrant, ...],
        now_ms: int,
    ) -> None:
        for grant in grants:
            if grant.task_id != task.id:
                raise TaskContextError("artifact grant task_id must match context task_id")
            if now_ms >= grant.expires_at_ms:
                raise TaskContextError("artifact grant is already expired")

    def _require_caller(self, task: Task, caller_agent_id: AgentId) -> None:
        if caller_agent_id not in (task.worker_id, task.mentor_id):
            raise TaskContextError("caller cannot read this task context")


# ---- scope ------------------------------------------------------------------
def _within_scope(path: ProjectPath, scopes: tuple[ProjectPath, ...]) -> bool:
    for scope in scopes:
        if path.value == scope.value or path.value.startswith(f"{scope.value}/"):
            return True
    return False

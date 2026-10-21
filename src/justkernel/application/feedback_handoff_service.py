"""Feedback package construction and worker handoff."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.agent import AgentInstance
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.ports import (
    CandidateRepositoryPort,
    TaskRepositoryPort,
    TestRecordRepositoryPort,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import AgentId, CandidateId, TaskId, TestRecordId
from justkernel.task.context import (
    ArtifactGrant,
    CandidateRef,
    EmptyReason,
    FeedbackRef,
    HistoryEntry,
    SharedEvidence,
    TaskBudget,
    TaskContext,
)
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.record import TestRecord


# ---- errors -----------------------------------------------------------------
class HandoffError(JustKernelError):
    code = ErrorCode.HANDOFF_INVALID


# ---- HandoffResult ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class HandoffResult:
    old_worker: AgentInstance
    new_worker: AgentInstance
    task: Task
    context: TaskContext


# ---- FeedbackHandoffService -------------------------------------------------
class FeedbackHandoffService:
    def __init__(
        self,
        agents: AgentService,
        tasks: TaskRepositoryPort,
        candidates: CandidateRepositoryPort,
        records: TestRecordRepositoryPort,
    ) -> None:
        self.agents = agents
        self.tasks = tasks
        self.candidates = candidates
        self.records = records

    def handoff(
        self,
        *,
        mentor_id: AgentId,
        old_task_id: TaskId,
        failed_record_id: TestRecordId,
        base_candidate_id: CandidateId,
        budget: TaskBudget,
        objective: str,
        acceptance: tuple[str, ...],
        shared_evidence: tuple[SharedEvidence, ...] = (),
        resource_grants: tuple[ArtifactGrant, ...] = (),
        now_ms: int,
    ) -> HandoffResult:
        old_task, mentor, old_worker, candidate, record = self._prepare(
            mentor_id,
            old_task_id,
            base_candidate_id,
            failed_record_id,
        )
        old_worker = self._stop_old_worker(old_worker, mentor, old_task, now_ms)
        context, new_task_id = self._build_context(
            old_task,
            candidate,
            record,
            budget,
            objective,
            acceptance,
            shared_evidence,
            resource_grants,
        )
        return self._dispatch(
            mentor,
            old_worker,
            old_task,
            candidate,
            context,
            new_task_id,
            now_ms,
        )

    def _prepare(
        self,
        mentor_id: AgentId,
        old_task_id: TaskId,
        base_candidate_id: CandidateId,
        failed_record_id: TestRecordId,
    ) -> tuple[Task, AgentInstance, AgentInstance, CandidateVersion, TestRecord]:
        old_task = self.tasks.get(old_task_id)
        mentor = self._mentor(mentor_id, old_task)
        old_worker = self.agents.get_agent(old_task.worker_id)
        self._check_old_worker(old_worker, mentor, old_task)
        candidate = self._candidate(old_task, base_candidate_id)
        record = self._record(candidate, failed_record_id)
        return old_task, mentor, old_worker, candidate, record

    def _dispatch(
        self,
        mentor: AgentInstance,
        old_worker: AgentInstance,
        old_task: Task,
        candidate: CandidateVersion,
        context: TaskContext,
        new_task_id: TaskId,
        now_ms: int,
    ) -> HandoffResult:
        new_worker = self.agents.open_worker(
            mentor_id=mentor.id,
            role=Role.OPTIMIZER,
            model_profile=old_worker.model_profile,
            skills=old_worker.skills,
            created_at=now_ms,
        )
        task = self.agents.assign_task(
            mentor_id=mentor.id,
            worker_id=new_worker.id,
            kind=TaskKind.OPTIMIZE,
            direction_id=old_task.direction_id,
            operator_spec_ref=old_task.operator_spec_ref,
            context_ref=f"artifact://task-context/{new_task_id.value}",
            context_digest=context.digest(),
            budget_ref=old_task.budget_ref,
            objective=context.objective,
            constraints=old_task.constraints,
            candidate_id=candidate.id,
            retry_of_task_id=old_task.id,
            task_id=new_task_id,
            created_at=now_ms,
        )
        return HandoffResult(old_worker, new_worker, task, context)

    def _mentor(self, mentor_id: AgentId, task: Task) -> AgentInstance:
        if task.mentor_id != mentor_id:
            raise HandoffError("task does not belong to this mentor")
        mentor = self.agents.get_agent(mentor_id)
        if mentor.role is not Role.MENTOR or mentor.state is AgentState.CLOSED:
            raise HandoffError("handoff requires an open mentor")
        return mentor

    def _check_old_worker(
        self,
        worker: AgentInstance,
        mentor: AgentInstance,
        task: Task,
    ) -> None:
        if worker.mentor_id != mentor.id or worker.cluster_id != task.cluster_id:
            raise HandoffError("old worker is not owned by this mentor")
        if worker.role is not Role.OPTIMIZER:
            raise HandoffError("handoff requires an optimizer worker")
        if worker.current_task_id not in (None, task.id):
            raise HandoffError("old worker is running another task")

    def _candidate(self, task: Task, candidate_id: CandidateId) -> CandidateVersion:
        try:
            candidate = self.candidates.get(candidate_id)
        except KeyError as error:
            raise HandoffError("base candidate does not exist") from error
        if candidate.cluster_id != task.cluster_id:
            raise HandoffError("base candidate belongs to another cluster")
        return candidate

    def _record(self, candidate: CandidateVersion, record_id: TestRecordId) -> TestRecord:
        try:
            record = self.records.get(record_id)
        except KeyError as error:
            raise HandoffError("failed record does not exist") from error
        if record.candidate_id != candidate.id:
            raise HandoffError("failed record belongs to another candidate")
        return record

    def _stop_old_worker(
        self,
        worker: AgentInstance,
        mentor: AgentInstance,
        task: Task,
        now_ms: int,
    ) -> AgentInstance:
        if worker.state is AgentState.RUNNING:
            self.agents.fail_task(
                mentor_id=mentor.id,
                task_id=task.id,
                reason="superseded by handoff",
                now_ms=now_ms,
            )
        return self.agents.close_worker(
            mentor_id=mentor.id,
            worker_id=worker.id,
            now_ms=now_ms,
        )

    def _build_context(
        self,
        old_task: Task,
        candidate: CandidateVersion,
        record: TestRecord,
        budget: TaskBudget,
        objective: str,
        acceptance: tuple[str, ...],
        shared_evidence: tuple[SharedEvidence, ...],
        resource_grants: tuple[ArtifactGrant, ...],
    ) -> tuple[TaskContext, TaskId]:
        new_task_id = self.agents.ids.task_id()
        context = self._context(
            old_task,
            candidate,
            record,
            new_task_id,
            budget,
            objective,
            acceptance,
            shared_evidence,
            resource_grants,
        )
        return context, new_task_id

    def _context(
        self,
        task: Task,
        candidate: CandidateVersion,
        record: TestRecord,
        new_task_id: TaskId,
        budget: TaskBudget,
        objective: str,
        acceptance: tuple[str, ...],
        shared_evidence: tuple[SharedEvidence, ...],
        resource_grants: tuple[ArtifactGrant, ...],
    ) -> TaskContext:
        empty_reasons = []
        if not shared_evidence:
            empty_reasons.append(EmptyReason("shared_evidence", "no shared evidence"))
        if not resource_grants:
            empty_reasons.append(EmptyReason("resource_grants", "no artifacts granted"))
        return TaskContext(
            task_id=new_task_id,
            operator_spec_ref=task.operator_spec_ref,
            base_candidate_ref=CandidateRef(candidate.id, candidate.source.digest),
            objective=objective,
            acceptance=acceptance,
            feedback=(self._feedback(task, record),),
            history=(self._history(task, candidate, record),),
            shared_evidence=shared_evidence,
            resource_grants=resource_grants,
            budget=budget,
            empty_reasons=tuple(empty_reasons),
        )

    def _feedback(self, task: Task, record: TestRecord) -> FeedbackRef:
        return FeedbackRef(
            summary=record.summary or "validation failed",
            record_id=record.id,
            task_id=task.id,
            artifact_ref=record.artifact.ref,
            failure_stage="test",
        )

    def _history(
        self,
        task: Task,
        candidate: CandidateVersion,
        record: TestRecord,
    ) -> HistoryEntry:
        return HistoryEntry(
            candidate_id=candidate.id,
            source_digest=candidate.source.digest,
            hypothesis=task.objective,
            result="validation failed",
            rejected_reason=record.summary or "test failed",
        )

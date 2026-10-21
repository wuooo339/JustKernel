"""Application service for ToolJobs and TestRecord sealing."""

from __future__ import annotations

from dataclasses import replace

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.ports import (
    AgentRepositoryPort,
    IdFactoryPort,
    TaskRepositoryPort,
    TestRecordRepositoryPort,
    ToolBackendPort,
    ToolJobRepositoryPort,
)
from justkernel.shared.digest import Digest
from justkernel.shared.ids import CandidateId, TaskId
from justkernel.shared.json import digest_json
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task
from justkernel.testing.errors import TestRecordError
from justkernel.testing.job import ToolJob, ToolJobError, ToolJobState
from justkernel.testing.record import ArtifactRef, Environment, TestRecord
from justkernel.testing.state import TestCoverage, TestOutcome, TestRecordKind


# ---- TestingService --------------------------------------------------------
class TestingService:
    def __init__(
        self,
        tasks: TaskRepositoryPort,
        agents: AgentRepositoryPort,
        records: TestRecordRepositoryPort,
        jobs: ToolJobRepositoryPort,
        backend: ToolBackendPort,
        ids: IdFactoryPort,
    ) -> None:
        self.tasks = tasks
        self.agents = agents
        self.records = records
        self.jobs = jobs
        self.backend = backend
        self.ids = ids

    def submit_test(
        self,
        *,
        task_id: TaskId,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None = None,
    ) -> ToolJob:
        return self._submit(task_id, TaskKind.TEST, Role.TESTER, case_selection, timeout_s, device)

    def submit_profile(
        self,
        *,
        task_id: TaskId,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None = None,
    ) -> ToolJob:
        return self._submit(
            task_id, TaskKind.PROFILE, Role.PROFILER, case_selection, timeout_s, device
        )

    def seal_record(
        self,
        *,
        task_id: TaskId,
        outcome: TestOutcome,
        coverage: TestCoverage,
        artifact: ArtifactRef,
        environment: Environment,
        backend: str,
        created_at: int,
        summary: str = "",
    ) -> TestRecord:
        task, job = self._seal_source(task_id)
        candidate_id, skill_ref = self._record_inputs(task)
        record = self._executed_record(
            task,
            job,
            candidate_id,
            skill_ref,
            outcome,
            coverage,
            artifact,
            environment,
            backend,
            created_at,
            summary,
        )
        self.records.append(record)
        self.jobs.update(replace(job, state=ToolJobState.SUCCEEDED, record_id=record.id.value))
        return record

    def _seal_source(self, task_id: TaskId) -> tuple[Task, ToolJob]:
        task = self.tasks.get(task_id)
        if task.kind not in (TaskKind.TEST, TaskKind.PROFILE):
            raise TestRecordError("task is not a testing task")
        job = self.jobs.get_by_task(task.id)
        if job is None:
            raise TestRecordError("task has no tool job")
        if self.records.get_by_task(task.id) is not None:
            raise TestRecordError("task already has a terminal record")
        return task, job

    def _record_inputs(self, task: Task) -> tuple[CandidateId, SkillRef]:
        candidate_id = task.candidate_id
        skill_ref = task.skill_ref
        if candidate_id is None or skill_ref is None:
            raise TestRecordError("testing task requires candidate and skill")
        return candidate_id, skill_ref

    def _executed_record(
        self,
        task: Task,
        job: ToolJob,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        outcome: TestOutcome,
        coverage: TestCoverage,
        artifact: ArtifactRef,
        environment: Environment,
        backend: str,
        created_at: int,
        summary: str,
    ) -> TestRecord:
        kind = TestRecordKind.TEST if task.kind is TaskKind.TEST else TestRecordKind.PROFILE
        return TestRecord(
            id=self.ids.test_record_id(),
            candidate_id=candidate_id,
            kind=kind,
            skill_ref=skill_ref,
            backend=backend,
            outcome=outcome,
            coverage=coverage,
            executed=True,
            artifact=artifact,
            environment=environment,
            created_at=created_at,
            task_id=task.id,
            job_id=job.id,
            summary=summary,
        )

    def seal_audit(
        self,
        *,
        candidate_id: CandidateId,
        kind: TestRecordKind,
        skill_ref: SkillRef,
        outcome: TestOutcome,
        audit_id: str,
        artifact: ArtifactRef,
        environment: Environment,
        created_at: int,
        summary: str = "",
    ) -> TestRecord:
        record = TestRecord(
            id=self.ids.test_record_id(),
            candidate_id=candidate_id,
            kind=kind,
            skill_ref=skill_ref,
            backend="audit",
            outcome=outcome,
            coverage=TestCoverage.NONE,
            executed=False,
            artifact=artifact,
            environment=environment,
            created_at=created_at,
            audit_id=audit_id,
            summary=summary,
        )
        self.records.append(record)
        return record

    def _submit(
        self,
        task_id: TaskId,
        expected_kind: TaskKind,
        expected_role: Role,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None,
    ) -> ToolJob:
        task = self._submit_task(task_id, expected_kind, expected_role)
        candidate_id, skill_ref = self._submit_inputs(task)
        request = self._request_digest(
            task.id,
            candidate_id,
            skill_ref.name,
            case_selection,
            timeout_s,
            device,
            expected_kind,
        )
        existing = self.jobs.get_by_task(task.id)
        if existing is not None:
            if existing.request_digest == request:
                return existing
            raise ToolJobError("conflicting tool job request")
        return self._new_job(task, candidate_id, request, case_selection, timeout_s, device)

    def _submit_task(self, task_id: TaskId, expected_kind: TaskKind, expected_role: Role) -> Task:
        task = self.tasks.get(task_id)
        if task.kind is not expected_kind or task.state is not TaskState.RUNNING:
            raise ToolJobError("tool job requires a running matching task")
        worker = self.agents.get(task.worker_id)
        if worker.role is not expected_role:
            raise ToolJobError("tool job worker role mismatch")
        return task

    def _submit_inputs(self, task: Task) -> tuple[CandidateId, SkillRef]:
        candidate_id = task.candidate_id
        skill_ref = task.skill_ref
        if candidate_id is None or skill_ref is None:
            raise ToolJobError("tool job requires candidate and skill")
        return candidate_id, skill_ref

    def _new_job(
        self,
        task: Task,
        candidate_id: CandidateId,
        request: Digest,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None,
    ) -> ToolJob:
        job = ToolJob(
            id=self._backend_job(task, candidate_id, case_selection, timeout_s, device),
            task_id=task.id,
            candidate_id=candidate_id,
            request_digest=request,
            state=ToolJobState.QUEUED,
            created_at=task.created_at,
        )
        self.jobs.insert(job)
        return job

    def _backend_job(
        self,
        task: Task,
        candidate_id: CandidateId,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None,
    ) -> str:
        assert task.skill_ref is not None
        if task.kind is TaskKind.TEST:
            return self.backend.submit_test(
                task_id=task.id,
                candidate_id=candidate_id,
                skill_ref=task.skill_ref,
                case_selection=case_selection,
                timeout_s=timeout_s,
                device=device,
            )
        return self.backend.submit_profile(
            task_id=task.id,
            candidate_id=candidate_id,
            skill_ref=task.skill_ref,
            case_selection=case_selection,
            timeout_s=timeout_s,
            device=device,
        )

    def _request_digest(
        self,
        task_id: TaskId,
        candidate_id: CandidateId,
        skill_name: str,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None,
        kind: TaskKind,
    ) -> Digest:
        return digest_json(
            {
                "kind": kind.value,
                "task": task_id.value,
                "candidate": candidate_id.value,
                "skill": skill_name,
                "cases": list(case_selection),
                "timeout": timeout_s,
                "device": device,
            }
        )

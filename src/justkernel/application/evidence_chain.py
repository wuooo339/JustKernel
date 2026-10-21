"""Evidence-chain sealing and archive verification."""

from __future__ import annotations

from collections.abc import Mapping

from justkernel.agent.skills import SkillRef
from justkernel.application.ports import ArtifactStorePort
from justkernel.application.testing_service import TestingService
from justkernel.shared.digest import Digest
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import CandidateId, TaskId, TestRecordId
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task
from justkernel.testing.errors import TestRecordError
from justkernel.testing.job import ToolJob
from justkernel.testing.record import ArtifactRef, Environment, TestRecord
from justkernel.testing.record_zip import build_record_zip, validate_record_zip
from justkernel.testing.state import TestCoverage, TestOutcome, TestRecordKind


# ---- EvidenceError ----------------------------------------------------------
class EvidenceError(TestRecordError):
    pass


# ---- EvidenceGate -----------------------------------------------------------
class EvidenceGate:
    def __init__(self, artifacts: ArtifactStorePort) -> None:
        self.artifacts = artifacts

    def require(self, record: TestRecord) -> None:
        try:
            data = self.artifacts.get_bytes(record.artifact.digest)
            validation = validate_record_zip(data, expected_record_id=record.id.value)
        except JustKernelError as error:
            raise EvidenceError("record archive is missing or invalid") from error
        if not self._matches(record, validation.manifest):
            raise EvidenceError("record does not match its archive")

    def _matches(self, record: TestRecord, manifest: Mapping[str, object]) -> bool:
        expected = {
            "record_id": record.id.value,
            "candidate_id": record.candidate_id.value,
            "task_id": record.task_id.value if record.task_id else None,
            "job_id": record.job_id,
            "audit_id": record.audit_id,
            "kind": record.kind.value,
            "backend": record.backend,
            "outcome": record.outcome.value,
            "executed": record.executed,
            "coverage": record.coverage.value,
            "environment": dict(record.environment.values),
            "skill": {
                "name": record.skill_ref.name,
                "version": record.skill_ref.version,
                "digest": record.skill_ref.digest.value,
            },
        }
        return all(manifest.get(key) == value for key, value in expected.items())


# ---- EvidenceChainService ---------------------------------------------------
class EvidenceChainService:
    def __init__(self, testing: TestingService, artifacts: ArtifactStorePort) -> None:
        self.testing = testing
        self.artifacts = artifacts

    def seal_archive(
        self,
        *,
        task_id: TaskId,
        cluster_id: str,
        payloads: Mapping[str, bytes | str],
        outcome: TestOutcome,
        coverage: TestCoverage,
        environment: Environment,
        backend: str,
        created_at: int,
        extra_manifest: Mapping[str, object] | None = None,
        summary: str = "",
    ) -> TestRecord:
        task, job, candidate_id, skill_ref = self._source(task_id)
        record_id = self.testing.ids.test_record_id()
        draft = self._draft(
            task,
            job,
            candidate_id,
            skill_ref,
            record_id,
            outcome,
            coverage,
            environment,
            backend,
            created_at,
            summary,
        )
        data = build_record_zip(
            draft,
            cluster_id=cluster_id,
            payloads=payloads,
            extra_manifest=extra_manifest,
        )
        validate_record_zip(data, expected_record_id=record_id.value)
        digest = self.artifacts.put_bytes(data)
        return self._persist(draft, digest, created_at)

    def _persist(
        self,
        draft: TestRecord,
        digest: Digest,
        created_at: int,
    ) -> TestRecord:
        if draft.task_id is None:
            raise TestRecordError("executed record lost its task id")
        return self.testing.seal_record(
            task_id=draft.task_id,
            outcome=draft.outcome,
            coverage=draft.coverage,
            artifact=ArtifactRef(ref=self.artifacts.ref_for(digest), digest=digest),
            environment=draft.environment,
            backend=draft.backend,
            created_at=created_at,
            summary=draft.summary,
            record_id=draft.id,
        )

    def _draft(
        self,
        task: Task,
        job: ToolJob,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        record_id: TestRecordId,
        outcome: TestOutcome,
        coverage: TestCoverage,
        environment: Environment,
        backend: str,
        created_at: int,
        summary: str,
    ) -> TestRecord:
        kind = TestRecordKind.TEST if task.kind is TaskKind.TEST else TestRecordKind.PROFILE
        return TestRecord(
            id=record_id,
            candidate_id=candidate_id,
            kind=kind,
            skill_ref=skill_ref,
            backend=backend,
            outcome=outcome,
            coverage=coverage,
            executed=True,
            artifact=ArtifactRef(ref="pending", digest=Digest.from_text("pending")),
            environment=environment,
            created_at=created_at,
            task_id=task.id,
            job_id=job.id,
            summary=summary,
        )

    def _source(self, task_id: TaskId) -> tuple[Task, ToolJob, CandidateId, SkillRef]:
        task = self.testing.tasks.get(task_id)
        if task.kind not in (TaskKind.TEST, TaskKind.PROFILE):
            raise TestRecordError("evidence task must be TEST or PROFILE")
        if task.state is not TaskState.RUNNING:
            raise TestRecordError("evidence task is not running")
        job = self.testing.jobs.get_by_task(task_id)
        if job is None:
            raise TestRecordError("evidence task has no job")
        if job.state.value != "RUNNING":
            raise TestRecordError("evidence job is not running")
        if task.candidate_id is None or task.skill_ref is None:
            raise TestRecordError("evidence task requires candidate and skill")
        return task, job, task.candidate_id, task.skill_ref

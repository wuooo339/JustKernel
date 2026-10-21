"""Manual cluster resume and late-result archival."""

from __future__ import annotations

from justkernel.application.ports import (
    ClusterRepositoryPort,
    IdFactoryPort,
    TaskRepositoryPort,
    TestRecordRepositoryPort,
    ToolJobRepositoryPort,
)
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.state import ClusterState
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import ClusterId, TaskId
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task
from justkernel.testing.job import ToolJob, ToolJobState
from justkernel.testing.record import ArtifactRef, Environment, TestRecord
from justkernel.testing.state import TestCoverage, TestOutcome, TestRecordKind


# ---- errors -----------------------------------------------------------------
class ResumeError(JustKernelError):
    code = ErrorCode.RESUME_INVALID


# ---- ResumeService ----------------------------------------------------------
class ResumeService:
    def __init__(
        self,
        clusters: ClusterRepositoryPort,
        tasks: TaskRepositoryPort,
        jobs: ToolJobRepositoryPort,
        records: TestRecordRepositoryPort,
        ids: IdFactoryPort,
    ) -> None:
        self.clusters = clusters
        self.tasks = tasks
        self.jobs = jobs
        self.records = records
        self.ids = ids

    def resume(self, cluster_id: ClusterId, *, now_ms: int) -> Cluster:
        cluster = self.clusters.get(cluster_id)
        if cluster.state is not ClusterState.PAUSED:
            raise ResumeError("resume requires a paused cluster")
        if now_ms < cluster.created_at:
            raise ResumeError("resume time precedes cluster creation")
        cluster.resume()
        version = self.clusters.version(cluster.id)
        self.clusters.update(cluster, expected_version=version)
        return cluster

    def archive_late_result(
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
        task, job = self._late_source(task_id)
        assert task.candidate_id is not None and task.skill_ref is not None
        record = TestRecord(
            id=self.ids.test_record_id(),
            candidate_id=task.candidate_id,
            kind=TestRecordKind.TEST if task.kind is TaskKind.TEST else TestRecordKind.PROFILE,
            skill_ref=task.skill_ref,
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
            late_completion=True,
        )
        self.records.append(record)
        return record

    def _late_source(self, task_id: TaskId) -> tuple[Task, ToolJob]:
        task = self.tasks.get(task_id)
        if task.state is not TaskState.INTERRUPTED:
            raise ResumeError("late result requires an interrupted task")
        if task.kind not in (TaskKind.TEST, TaskKind.PROFILE):
            raise ResumeError("late result requires a testing task")
        job = self.jobs.get_by_task(task.id)
        if job is None or job.state is not ToolJobState.INTERRUPTED:
            raise ResumeError("late result requires an interrupted job")
        if task.candidate_id is None or task.skill_ref is None:
            raise ResumeError("late result requires candidate and skill")
        if self.records.get_by_task(task.id) is not None:
            raise ResumeError("task already has a terminal record")
        return task, job

from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.agent_service import AgentService
from justkernel.application.best_report_service import BestSelectionService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    FakeToolBackend,
    InMemoryAgentRepository,
    InMemoryBestSelectionRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.application.resume_service import ResumeError, ResumeService
from justkernel.application.testing_service import TestingService as Service
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import BestSelectionError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import ClusterState, StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, DirectionId
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation-test",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(ref="artifact://late", digest=Digest.from_text("late zip"))


def _environment() -> Environment:
    return Environment(values=(("soc", "Ascend910B4"),))


def _stack() -> tuple[
    ResumeService,
    ClusterService,
    AgentService,
    Task,
    AgentInstance,
    CandidateVersion,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
    object,
    object,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    object,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    jobs = InMemoryToolJobRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
    backend = FakeToolBackend()
    testing = Service(tasks, agents, records, jobs, backend, ids)
    cluster = cluster_service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    cluster_service.start_cluster(cluster.id)
    agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.SUPERVISOR,
        model_profile="model-1",
        skills=(),
        agent_id=cluster.supervisor_id,
    )
    mentor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.MENTOR,
        model_profile="model-1",
        skills=(),
    )
    tester = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(),
    )
    candidate = candidate_service.import_candidate(
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// root"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    task = agent_service.assign_task(
        mentor_id=mentor.id,
        worker_id=tester.id,
        kind=TaskKind.TEST,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="test",
        candidate_id=candidate.id,
        skill_ref=_skill(),
        created_at=0,
    )
    job = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)
    testing.start_job(job.id, now_ms=0)
    agent_service.interrupt_task(
        mentor_id=mentor.id,
        task_id=task.id,
        reason="control restart",
        now_ms=10,
    )
    testing.interrupt_job(job.id, reason="control restart", now_ms=10)
    cluster_service.pause_cluster(cluster.id)
    resume = ResumeService(clusters, tasks, jobs, records, ids)
    return (
        resume,
        cluster_service,
        agent_service,
        task,
        tester,
        candidate,
        records,
        jobs,
        job,
        cluster,
        candidates,
        clusters,
        ids,
    )


def _late(resume: ResumeService, task: Task) -> object:
    return resume.archive_late_result(
        task_id=task.id,
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        artifact=_artifact(),
        environment=_environment(),
        backend="cann-simulation",
        created_at=20,
        summary="late result",
    )


# ---- resume -----------------------------------------------------------------
def test_resume_only_mutates_cluster_state() -> None:
    resume, clusters, _, task, _, _, records, jobs, job, cluster, _, _, _ = _stack()

    resumed = resume.resume(cluster.id, now_ms=20)

    assert resumed.state is ClusterState.RUNNING
    assert clusters.get(cluster.id).state is ClusterState.RUNNING
    assert task.state is TaskState.INTERRUPTED
    assert jobs.get(job.id).state.value == "INTERRUPTED"
    assert records.get_by_task(task.id) is None


def test_resume_rejects_non_paused_cluster() -> None:
    resume, _, _, _, _, _, _, _, _, cluster, _, _, _ = _stack()
    resume.resume(cluster.id, now_ms=20)

    with pytest.raises(ResumeError):
        resume.resume(cluster.id, now_ms=30)


# ---- late results -----------------------------------------------------------
def test_late_result_is_bound_but_not_full_pass() -> None:
    resume, _, _, task, _, candidate, records, jobs, job, _, _, _, _ = _stack()

    record = _late(resume, task)

    assert record.late_completion is True
    assert record.task_id == task.id
    assert record.job_id == job.id
    assert record.candidate_id == candidate.id
    assert record.is_full_pass is False
    assert records.get_by_task(task.id) == record
    assert task.state is TaskState.INTERRUPTED
    assert jobs.get(job.id).state.value == "INTERRUPTED"

    with pytest.raises(ResumeError):
        _late(resume, task)


def test_late_full_pass_cannot_be_nominated() -> None:
    resume, _, _, task, _, candidate, records, _, _, cluster, candidates, clusters, _ = _stack()
    record = _late(resume, task)
    best = BestSelectionService(
        clusters,
        candidates,
        records,
        InMemoryBestSelectionRepository(),
        FakeIds(),
    )

    with pytest.raises(BestSelectionError):
        best.nominate_best(
            cluster_id=cluster.id,
            candidate_id=candidate.id,
            policy_digest=Digest.from_text("policy"),
            nomination_record_ids=(record.id,),
            reason="late",
            created_at=20,
        )


def test_late_result_requires_interrupted_task_and_matching_job() -> None:
    resume, _, _, task, _, _, _, _, _, _, _, _, _ = _stack()
    _late(resume, task)

    with pytest.raises(ResumeError):
        resume.archive_late_result(
            task_id=task.id,
            outcome=Outcome.PASS,
            coverage=Coverage.FULL,
            artifact=_artifact(),
            environment=_environment(),
            backend="cann-simulation",
            created_at=30,
        )

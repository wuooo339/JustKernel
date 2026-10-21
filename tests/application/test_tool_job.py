from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    FakeToolBackend,
    InMemoryAgentRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.application.testing_service import TestingService as Service
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.errors import TestRecordError as RecordError
from justkernel.testing.job import ToolJobError, ToolJobState
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
        name="cann-simulation",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(ref="artifact://record", digest=Digest.from_text("zip"))


def _environment() -> Environment:
    return Environment(values=(("soc", "Ascend910B4"),))


def _stack() -> tuple[
    Service,
    AgentService,
    InMemoryToolJobRepository,
    InMemoryTestRecordRepository,
    AgentInstance,
    AgentInstance,
    AgentInstance,
    FakeIds,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    records = InMemoryTestRecordRepository()
    jobs = InMemoryToolJobRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
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
    other = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(),
    )
    service = Service(tasks, agents, records, jobs, FakeToolBackend(), ids, queue_timeout_s=600)
    return service, agent_service, jobs, records, mentor, tester, other, ids


def _task(
    agents: AgentService,
    mentor: AgentInstance,
    worker: AgentInstance,
    kind: TaskKind = TaskKind.TEST,
) -> Task:
    return agents.assign_task(
        mentor_id=mentor.id,
        worker_id=worker.id,
        kind=kind,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="tool job",
        candidate_id=CandidateId.generate(),
        skill_ref=_skill(),
        created_at=0,
    )


# ---- submission -------------------------------------------------------------
def test_submit_is_idempotent_and_rejects_conflicts() -> None:
    testing, agents, jobs, _, mentor, tester, _, _ = _stack()
    task = _task(agents, mentor, tester)

    first = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)
    second = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)

    assert first == second
    assert first.state is ToolJobState.QUEUED
    assert first.queue_expires_at == 600
    assert first.execution_timeout_s == 30
    assert jobs.get_by_task(task.id) == first

    with pytest.raises(ToolJobError):
        testing.submit_test(task_id=task.id, case_selection=("case-2",), timeout_s=30)
    with pytest.raises(ToolJobError):
        testing.submit_profile(task_id=task.id, case_selection=("case-1",), timeout_s=30)


def test_queue_timeout_is_anchored_at_submission() -> None:
    testing, agents, _, _, mentor, tester, _, _ = _stack()
    task = _task(agents, mentor, tester)

    job = testing.submit_test(
        task_id=task.id,
        case_selection=("case-1",),
        timeout_s=30,
        now_ms=500,
    )

    assert job.created_at == 500
    assert job.queue_expires_at == 1_100
    assert testing.start_job(job.id, now_ms=1_099).state is ToolJobState.RUNNING


# ---- lifecycle transitions --------------------------------------------------
def test_queue_timeout_fails_job() -> None:
    testing, agents, _, _, mentor, tester, _, _ = _stack()
    task = _task(agents, mentor, tester)
    job = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)

    failed = testing.timeout_job(job.id, now_ms=600)

    assert failed.state is ToolJobState.FAILED
    assert failed.error == "queue timeout"
    assert failed.finished_at == 600
    assert failed.queue_position is None

    with pytest.raises(ToolJobError):
        testing.start_job(job.id, now_ms=601)
    with pytest.raises(ToolJobError):
        testing.timeout_job(job.id, now_ms=602)


def test_execution_timeout_starts_when_running() -> None:
    testing, agents, _, _, mentor, tester, _, _ = _stack()
    task = _task(agents, mentor, tester)
    job = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)

    running = testing.start_job(job.id, now_ms=10)
    assert running.state is ToolJobState.RUNNING
    assert running.started_at == 10
    assert running.queue_position is None

    with pytest.raises(ToolJobError):
        testing.timeout_job(job.id, now_ms=39)
    failed = testing.timeout_job(job.id, now_ms=40)
    assert failed.state is ToolJobState.FAILED
    assert failed.error == "execution timeout"


def test_cancel_interrupt_and_fail_are_terminal() -> None:
    testing, agents, _, _, mentor, tester, other, _ = _stack()
    third = agents.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(),
    )
    cancelled_task = _task(agents, mentor, tester)
    interrupted_task = _task(agents, mentor, other)
    failed_task = _task(agents, mentor, third)
    cancelled = testing.submit_test(
        task_id=cancelled_task.id, case_selection=("case-1",), timeout_s=30
    )
    interrupted = testing.submit_test(
        task_id=interrupted_task.id, case_selection=("case-1",), timeout_s=30
    )
    failed_job = testing.submit_test(
        task_id=failed_task.id, case_selection=("case-1",), timeout_s=30
    )

    assert testing.cancel_job(cancelled.id, reason="cancelled", now_ms=1).state is (
        ToolJobState.CANCELLED
    )
    assert testing.interrupt_job(interrupted.id, reason="interrupted", now_ms=2).state is (
        ToolJobState.INTERRUPTED
    )
    assert testing.start_job(failed_job.id, now_ms=3).state is ToolJobState.RUNNING
    assert testing.fail_job(failed_job.id, error="backend failed", now_ms=4).state is (
        ToolJobState.FAILED
    )

    for job_id in (cancelled.id, interrupted.id, failed_job.id):
        with pytest.raises(ToolJobError):
            testing.cancel_job(job_id, reason="again", now_ms=5)


def test_seal_requires_running_job() -> None:
    testing, agents, jobs, _, mentor, tester, _, _ = _stack()
    task = _task(agents, mentor, tester)
    job = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)

    with pytest.raises(RecordError):
        testing.seal_record(
            task_id=task.id,
            outcome=Outcome.PASS,
            coverage=Coverage.FULL,
            artifact=_artifact(),
            environment=_environment(),
            backend="cann-simulation",
            created_at=100,
        )

    testing.start_job(job.id, now_ms=0)
    record = testing.seal_record(
        task_id=task.id,
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        artifact=_artifact(),
        environment=_environment(),
        backend="cann-simulation",
        created_at=100,
    )

    completed = jobs.get(job.id)
    assert record.id.value == completed.record_id
    assert completed.state is ToolJobState.SUCCEEDED
    assert completed.finished_at == 100


# ---- owner-only reads -------------------------------------------------------
def test_read_tool_job_is_owner_only() -> None:
    testing, agents, _, _, mentor, tester, other, _ = _stack()
    task = _task(agents, mentor, tester)
    job = testing.submit_test(task_id=task.id, case_selection=("case-1",), timeout_s=30)

    view = testing.read_tool_job(job.id, caller_agent_id=tester.id)
    assert view.job_id == job.id
    assert view.task_id == task.id
    assert view.state is ToolJobState.QUEUED
    assert view.queue_position == 1

    with pytest.raises(ToolJobError):
        testing.read_tool_job(job.id, caller_agent_id=other.id)

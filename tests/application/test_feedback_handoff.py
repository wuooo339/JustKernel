from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
)
from justkernel.application.feedback_handoff_service import (
    FeedbackHandoffService,
    HandoffError,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.task.context import TaskBudget
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


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
        name="optimizer",
        version="1",
        source_path="/skills/optimizer",
        digest=Digest.from_text("skill"),
    )


def _record(candidate: CandidateVersion, task: Task) -> Record:
    return Record(
        id=RecordId.generate(),
        candidate_id=candidate.id,
        kind=RecordKind.TEST,
        skill_ref=_skill(),
        backend="cann-simulation",
        outcome=Outcome.FAIL,
        coverage=Coverage.FULL,
        executed=True,
        artifact=ArtifactRef(ref="artifact://failure", digest=Digest.from_text("failure zip")),
        environment=Environment(values=(("soc", "Ascend910B4"),)),
        created_at=0,
        task_id=TaskId.generate(),
        job_id="job-failure",
        summary="precision mismatch",
    )


def _stack(
    *,
    complete_old_task: bool = True,
) -> tuple[
    FeedbackHandoffService,
    AgentService,
    Task,
    AgentInstance,
    AgentInstance,
    CandidateVersion,
    Record,
    InMemoryTestRecordRepository,
]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
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
    old_worker = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile="model-1",
        skills=(_skill(),),
    )
    candidate = candidate_service.import_candidate(
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        source_files={"kernel.cpp": "// root"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        created_at=0,
    )
    old_task = agent_service.assign_task(
        mentor_id=mentor.id,
        worker_id=old_worker.id,
        kind=TaskKind.OPTIMIZE,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://old-context",
        context_digest=Digest.from_text("old-context"),
        budget_ref="budget-1",
        objective="first attempt",
        candidate_id=candidate.id,
        created_at=0,
    )
    record = _record(candidate, old_task)
    records.append(record)
    if complete_old_task:
        agent_service.complete_task(
            mentor_id=mentor.id,
            task_id=old_task.id,
            result_ref="artifact://old-result",
            now_ms=10,
        )
    service = FeedbackHandoffService(agent_service, tasks, candidates, records)
    return service, agent_service, old_task, mentor, old_worker, candidate, record, records


def _handoff(
    service: FeedbackHandoffService,
    task: Task,
    mentor: AgentInstance,
    candidate: CandidateVersion,
    record: Record,
    *,
    now_ms: int = 100,
) -> object:
    return service.handoff(
        mentor_id=mentor.id,
        old_task_id=task.id,
        failed_record_id=record.id,
        base_candidate_id=candidate.id,
        budget=TaskBudget(max_duration_s=100),
        objective="repair failed precision",
        acceptance=("full test passes",),
        now_ms=now_ms,
    )


# ---- handoff ----------------------------------------------------------------
def test_feedback_handoff_replaces_worker_and_preserves_context() -> None:
    service, agents, old_task, mentor, old_worker, candidate, record, records = _stack()

    result = _handoff(service, old_task, mentor, candidate, record)

    assert result.old_worker.state is AgentState.CLOSED
    assert result.new_worker.state is AgentState.RUNNING
    assert result.new_worker.id != old_worker.id
    assert result.task.worker_id == result.new_worker.id
    assert result.task.kind is TaskKind.OPTIMIZE
    assert result.task.state is TaskState.RUNNING
    assert result.task.retry_of_task_id == old_task.id
    assert result.task.candidate_id == candidate.id
    assert result.context.feedback[0].record_id == record.id
    assert result.context.feedback[0].artifact_ref == record.artifact.ref
    assert result.context.history[0].candidate_id == candidate.id
    assert result.context.base_candidate_ref is not None
    assert result.context.base_candidate_ref.candidate_id == candidate.id
    assert records.get(record.id) == record
    assert agents.get_agent(old_task.worker_id).state is AgentState.CLOSED


def test_running_old_task_is_failed_before_handoff() -> None:
    service, _, old_task, mentor, old_worker, candidate, record, _ = _stack(complete_old_task=False)

    result = _handoff(service, old_task, mentor, candidate, record)

    assert old_worker.state is AgentState.CLOSED
    assert old_task.state is TaskState.FAILED
    assert old_task.terminal_reason == "superseded by handoff"
    assert result.new_worker.state is AgentState.RUNNING


def test_foreign_failed_record_is_rejected_before_changes() -> None:
    service, agents, old_task, mentor, old_worker, candidate, record, _ = _stack()

    with pytest.raises(HandoffError):
        service.handoff(
            mentor_id=mentor.id,
            old_task_id=old_task.id,
            failed_record_id=record.id,
            base_candidate_id=CandidateId.generate(),
            budget=TaskBudget(max_duration_s=100),
            objective="repair",
            acceptance=("full test passes",),
            now_ms=100,
        )
    assert agents.get_agent(old_worker.id).state is AgentState.IDLE


def test_old_worker_must_belong_to_mentor() -> None:
    service, _, old_task, mentor, _, candidate, record, _ = _stack()
    other_mentor = AgentId.generate()

    with pytest.raises(HandoffError):
        service.handoff(
            mentor_id=other_mentor,
            old_task_id=old_task.id,
            failed_record_id=record.id,
            base_candidate_id=candidate.id,
            budget=TaskBudget(max_duration_s=100),
            objective="repair",
            acceptance=("full test passes",),
            now_ms=100,
        )

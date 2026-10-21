from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.agent import AgentInstance
from justkernel.agent.model_profile import ModelProfile
from justkernel.agent.model_routing import ModelRouting
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
    InMemoryModelProfileRegistry,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
)
from justkernel.application.feedback_handoff_service import FeedbackHandoffService
from justkernel.application.model_service import ModelRoutingService
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.comm.capabilities import BOARD_TOOLS, Tool, tools_for
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, DirectionId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.task.context import TaskBudget
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- profiles ---------------------------------------------------------------
def _profile(name: str, *, provider: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name,
        provider=provider,
        model=f"model-{name}",
        secret_ref="secret-ref",
    )


def _routing() -> ModelRoutingService:
    registry = InMemoryModelProfileRegistry()
    for name in ("system", "mentor", "optimizer-a", "optimizer-b", "tester", "fallback"):
        registry.add(_profile(name))
    routing = ModelRouting(
        system_default="system",
        role_defaults=(("MENTOR", "mentor"), ("TESTER", "tester")),
        direction_defaults=(("direction-1", "optimizer-a"),),
        allowed_fallbacks=("fallback",),
        provider_concurrency=(("openai", 4),),
        price_source="configured",
    )
    return ModelRoutingService(routing, registry)


@dataclass
class _Stack:
    agents: AgentService
    candidate_service: CandidateService
    records: InMemoryTestRecordRepository
    candidate: CandidateVersion
    mentor: AgentInstance
    optimizer: AgentInstance
    tester: AgentInstance
    task: Task
    record: Record


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


def _stack(service: ModelRoutingService) -> _Stack:
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
    mentor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.MENTOR,
        model_profile=service.resolve(Role.MENTOR).name,
        skills=(),
    )
    optimizer = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile=service.resolve(Role.OPTIMIZER, instance_profile="optimizer-a").name,
        skills=(),
    )
    tester = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile=service.resolve(Role.TESTER).name,
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
        worker_id=optimizer.id,
        kind=TaskKind.OPTIMIZE,
        direction_id=candidate.direction_id,
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="repair",
        candidate_id=candidate.id,
        created_at=0,
    )
    agent_service.complete_task(
        mentor_id=mentor.id,
        task_id=task.id,
        result_ref="artifact://result",
        now_ms=1,
    )
    record = Record(
        id=RecordId.generate(),
        candidate_id=candidate.id,
        kind=RecordKind.TEST,
        skill_ref=_skill(),
        backend="cann-simulation",
        outcome=Outcome.FAIL,
        coverage=Coverage.FULL,
        executed=True,
        artifact=ArtifactRef(ref="artifact://failure", digest=Digest.from_text("zip")),
        environment=Environment(values=(("soc", "Ascend910B4"),)),
        created_at=0,
        task_id=task.id,
        job_id="job-1",
    )
    records.append(record)
    return _Stack(
        agent_service,
        candidate_service,
        records,
        candidate,
        mentor,
        optimizer,
        tester,
        task,
        record,
    )


# ---- routing ----------------------------------------------------------------
def test_routing_priority_fallback_and_limits() -> None:
    service = _routing()

    assert service.resolve(Role.MENTOR).name == "mentor"
    assert service.resolve(Role.TESTER).name == "tester"
    assert service.resolve(Role.OPTIMIZER, direction_id="direction-1").name == "optimizer-a"
    assert (
        service.resolve(
            Role.OPTIMIZER,
            direction_id="direction-1",
            task_profile="optimizer-a",
            instance_profile="optimizer-b",
        ).name
        == "optimizer-b"
    )
    selection = service.fallback("optimizer-b", "provider outage")
    assert selection.fallback is True
    assert selection.profile.name == "fallback"
    assert selection.reason == "provider outage"
    assert service.provider_limit("openai") == 4
    assert service.routing.digest() == service.routing.digest()


# ---- agent binding and handoff ---------------------------------------------
def test_agents_bind_models_and_handoff_switches_without_losing_feedback() -> None:
    service = _routing()
    stack = _stack(service)
    assert stack.mentor.model_profile == "mentor"
    assert stack.optimizer.model_profile == "optimizer-a"
    assert stack.tester.model_profile == "tester"
    assert not (set(tools_for(Role.OPTIMIZER)) & BOARD_TOOLS)
    assert Tool.READ_TASK in tools_for(Role.OPTIMIZER)

    handoff = FeedbackHandoffService(
        stack.agents,
        stack.agents.tasks,
        stack.candidate_service.candidates,
        stack.records,
    )
    handed = handoff.handoff(
        mentor_id=stack.mentor.id,
        old_task_id=stack.task.id,
        failed_record_id=stack.record.id,
        base_candidate_id=stack.candidate.id,
        budget=TaskBudget(max_duration_s=100),
        objective="repair with a different model",
        acceptance=("full test passes",),
        now_ms=10,
        model_profile="optimizer-b",
    )

    assert handed.old_worker.state is AgentState.CLOSED
    assert handed.old_worker.model_profile == "optimizer-a"
    assert handed.new_worker.model_profile == "optimizer-b"
    assert handed.task.retry_of_task_id == stack.task.id
    assert handed.context.feedback[0].record_id == stack.record.id
    assert handed.context.history[0].candidate_id == stack.candidate.id
    assert handed.task.candidate_id == stack.candidate.id
    assert not (set(tools_for(Role.OPTIMIZER)) & BOARD_TOOLS)

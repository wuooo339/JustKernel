from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.errors import AgentError
from justkernel.agent.state import WORKER_ROLES, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryBudgetLedger,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
)
from justkernel.cluster.invariants import InvariantError
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.comm.acl import can_read, can_write
from justkernel.comm.capabilities import BOARD_TOOLS, Tool, can_use_tool, tools_for
from justkernel.comm.channels import Channel
from justkernel.comm.inbox import MessageInbox
from justkernel.comm.message import Message, MessageType
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, ClusterId, DirectionId, MessageId
from justkernel.shared.principal import Principal
from justkernel.task.state import TaskKind
from justkernel.task.task import Task


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _stack() -> tuple[AgentService, AgentInstance, AgentInstance, AgentInstance]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
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
    other_mentor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.MENTOR,
        model_profile="model-1",
        skills=(),
    )
    worker = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.OPTIMIZER,
        model_profile="model-1",
        skills=(),
    )
    return agent_service, mentor, other_mentor, worker


def _assign(service: AgentService, mentor: AgentInstance, worker: AgentInstance) -> Task:
    return service.assign_task(
        mentor_id=mentor.id,
        worker_id=worker.id,
        kind=TaskKind.GENERATE,
        direction_id=DirectionId.generate(),
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="generate",
        created_at=0,
    )


# ---- board ACL --------------------------------------------------------------
def test_worker_roles_have_no_board_access() -> None:
    board = Channel.mentor_board()

    for role in WORKER_ROLES:
        actor = Principal.agent(AgentId.generate())
        assert not can_read(role, actor, board)
        assert not can_write(role, actor, board)
        assert not (tools_for(role) & BOARD_TOOLS)


def test_consultant_reads_mentor_board_but_cannot_post() -> None:
    board = Channel.mentor_board()

    assert can_read(Role.CONSULTANT, Principal.agent(AgentId.generate()), board)
    assert not can_write(Role.CONSULTANT, Principal.agent(AgentId.generate()), board)
    assert can_use_tool(Role.CONSULTANT, Tool.READ_MENTOR_BOARD)
    assert not can_use_tool(Role.CONSULTANT, Tool.POST_MENTOR_BOARD)
    assert can_use_tool(Role.CONSULTANT, Tool.POST_CONSULTANT_BOARD)


# ---- tool/object capabilities ----------------------------------------------
def test_evidence_and_report_capabilities() -> None:
    assert not can_use_tool(Role.OPTIMIZER, Tool.READ_TEST_RECORD)
    assert not can_use_tool(Role.OPTIMIZER, Tool.READ_MENTOR_BOARD)
    assert not can_use_tool(Role.TESTER, Tool.WRITE_SOURCE)
    assert not can_use_tool(Role.TESTER, Tool.COMMIT_CANDIDATE)

    assert can_use_tool(Role.SUPERVISOR, Tool.SELECT_BEST)
    assert not can_use_tool(Role.MENTOR, Tool.SELECT_BEST)
    assert can_use_tool(Role.SUPERVISOR, Tool.WRITE_REPORT)
    assert can_use_tool(Role.MENTOR, Tool.ASSIGN_TASK)


# ---- mentor ownership -------------------------------------------------------
def test_mentor_cannot_assign_or_close_another_mentors_worker() -> None:
    service, mentor, other_mentor, worker = _stack()

    with pytest.raises(InvariantError):
        _assign(service, other_mentor, worker)
    with pytest.raises(AgentError):
        service.close_worker(
            mentor_id=other_mentor.id,
            worker_id=worker.id,
            now_ms=100,
        )

    _assign(service, mentor, worker)


# ---- idempotency ------------------------------------------------------------
def test_message_inbox_deduplicates_by_message_id() -> None:
    message = Message(
        id=MessageId.generate(),
        cluster_id=ClusterId.generate(),
        seq=1,
        channel=Channel.mentor_board(),
        type=MessageType.DIRECTION_ASSIGNED,
        sender=Principal.agent(AgentId.generate()),
        created_at=0,
    )
    inbox = MessageInbox()

    assert inbox.accept(message) is True
    assert inbox.accept(message) is False
    assert len(inbox) == 1


def test_budget_reserve_and_settle_are_idempotent() -> None:
    ledger = InMemoryBudgetLedger(limit=10)
    cluster = ClusterId.generate()

    assert ledger.reserve(cluster, 6, "key-1") is True
    assert ledger.reserve(cluster, 6, "key-1") is True
    assert ledger.available(cluster) == 4
    assert ledger.settle(cluster, 6, "key-1") is True
    assert ledger.settle(cluster, 6, "key-1") is True
    assert ledger.available(cluster) == 4

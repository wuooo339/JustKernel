from __future__ import annotations

import pytest

from justkernel.agent.state import WORKER_ROLES, Role
from justkernel.application.errors import ToolAccessError, ToolNotFoundError
from justkernel.application.tool_registry import (
    ObjectKind,
    ObjectRef,
    ToolContext,
    ToolRegistry,
)
from justkernel.comm.capabilities import BOARD_TOOLS, Tool, tools_for
from justkernel.shared.ids import AgentId, CandidateId, ClusterId, TaskId


# ---- helpers ----------------------------------------------------------------
def _context(role: Role, **overrides: object) -> ToolContext:
    values: dict[str, object] = {
        "role": role,
        "agent_id": AgentId.generate(),
        "cluster_id": ClusterId.generate(),
    }
    values.update(overrides)
    return ToolContext(**values)


def _ref(kind: ObjectKind, value: str = "object-1") -> ObjectRef:
    return ObjectRef(kind, value)


# ---- capability matrix ------------------------------------------------------
def test_available_matches_role_matrix() -> None:
    registry = ToolRegistry()

    for role in Role:
        assert frozenset(registry.available(role)) == tools_for(role)

    for role in WORKER_ROLES:
        assert not (set(registry.available(role)) & BOARD_TOOLS)


def test_worker_and_consultant_board_denials() -> None:
    registry = ToolRegistry()
    worker = _context(Role.OPTIMIZER)
    consultant = _context(Role.CONSULTANT)

    with pytest.raises(ToolAccessError):
        registry.authorize(worker, Tool.READ_MENTOR_BOARD, _ref(ObjectKind.BOARD))
    with pytest.raises(ToolAccessError):
        registry.authorize(consultant, Tool.POST_MENTOR_BOARD, _ref(ObjectKind.BOARD))

    registry.authorize(consultant, Tool.READ_MENTOR_BOARD, _ref(ObjectKind.BOARD))


# ---- object grants ----------------------------------------------------------
def test_task_scoped_grants_are_enforced() -> None:
    registry = ToolRegistry()
    candidate = CandidateId.generate().value
    task = TaskId.generate().value
    context = _context(
        Role.OPTIMIZER,
        allowed_candidates=frozenset({candidate}),
        allowed_tasks=frozenset({task}),
        allowed_artifacts=frozenset({"context-1"}),
    )

    registry.authorize(context, Tool.READ_CANDIDATE, _ref(ObjectKind.CANDIDATE, candidate))
    registry.authorize(context, Tool.READ_TASK, _ref(ObjectKind.TASK, task))
    registry.authorize(context, Tool.READ_TASK_CONTEXT, _ref(ObjectKind.CONTEXT, "context-1"))
    registry.authorize(context, Tool.READ_TASK_ARTIFACT, _ref(ObjectKind.ARTIFACT, "context-1"))

    with pytest.raises(ToolAccessError):
        registry.authorize(
            context,
            Tool.READ_CANDIDATE,
            _ref(ObjectKind.CANDIDATE, CandidateId.generate().value),
        )
    with pytest.raises(ToolAccessError):
        registry.authorize(context, Tool.READ_TASK, _ref(ObjectKind.TASK, TaskId.generate().value))


def test_record_grants_and_privileged_reads() -> None:
    registry = ToolRegistry()
    record = "record-1"
    tester = _context(
        Role.TESTER,
        allowed_records=frozenset({record}),
        allowed_tool_jobs=frozenset({"job-1"}),
    )
    supervisor = _context(Role.SUPERVISOR)

    registry.authorize(tester, Tool.READ_TEST_RECORD, _ref(ObjectKind.TEST_RECORD, record))
    registry.authorize(tester, Tool.READ_TOOL_JOB, _ref(ObjectKind.TOOL_JOB, "job-1"))
    with pytest.raises(ToolAccessError):
        registry.authorize(tester, Tool.READ_TOOL_JOB, _ref(ObjectKind.TOOL_JOB, "job-2"))
    with pytest.raises(ToolAccessError):
        registry.authorize(tester, Tool.READ_TEST_RECORD, _ref(ObjectKind.TEST_RECORD, "other"))

    registry.authorize(
        supervisor,
        Tool.READ_CANDIDATE,
        _ref(ObjectKind.CANDIDATE, CandidateId.generate().value),
    )


# ---- invocation -------------------------------------------------------------
def test_invoke_authorizes_before_handler() -> None:
    registry = ToolRegistry()
    calls: list[str] = []

    def handler(reference: ObjectRef) -> str:
        calls.append(reference.id)
        return reference.id

    candidate = CandidateId.generate().value
    registry.register(Tool.READ_CANDIDATE, handler)
    context = _context(Role.OPTIMIZER, allowed_candidates=frozenset({candidate}))

    assert (
        registry.invoke(context, Tool.READ_CANDIDATE, _ref(ObjectKind.CANDIDATE, candidate))
        == candidate
    )
    with pytest.raises(ToolAccessError):
        registry.invoke(
            context,
            Tool.READ_CANDIDATE,
            _ref(ObjectKind.CANDIDATE, CandidateId.generate().value),
        )
    assert calls == [candidate]


def test_missing_handler_is_rejected() -> None:
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError):
        registry.invoke(
            _context(Role.SUPERVISOR),
            Tool.WRITE_REPORT,
            _ref(ObjectKind.BOARD),
        )

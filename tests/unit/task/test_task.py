from __future__ import annotations

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    TaskId,
)
from justkernel.task.errors import TaskError
from justkernel.task.state import TaskKind, TaskState
from justkernel.task.task import Task


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="ConfusionMulGrad",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation",
        version="1",
        source_path="/skills/builtin/tester-cann-simulation",
        digest=Digest.from_text("skill"),
    )


def _task(kind: TaskKind = TaskKind.TEST, **overrides: object) -> Task:
    values: dict[str, object] = {
        "id": TaskId.generate(),
        "cluster_id": ClusterId.generate(),
        "mentor_id": AgentId.generate(),
        "worker_id": AgentId.generate(),
        "kind": kind,
        "direction_id": DirectionId.generate(),
        "operator_spec_ref": _operator_ref(),
        "context_ref": "artifact://context",
        "context_digest": Digest.from_text("context"),
        "budget_ref": "budget-1",
        "objective": "exercise the candidate",
        "created_at": 0,
    }
    if kind is not TaskKind.GENERATE:
        values["candidate_id"] = CandidateId.generate()
    if kind in (TaskKind.TEST, TaskKind.PROFILE):
        values["skill_ref"] = _skill()
    values.update(overrides)
    return Task(**values)


# ---- kind constraints -------------------------------------------------------
def test_all_task_kinds_are_valid() -> None:
    for kind in TaskKind:
        assert _task(kind).kind is kind


def test_kind_specific_requirements() -> None:
    with pytest.raises(TaskError):
        _task(TaskKind.GENERATE, candidate_id=CandidateId.generate())
    with pytest.raises(TaskError):
        _task(TaskKind.GENERATE, skill_ref=_skill())
    with pytest.raises(TaskError):
        _task(TaskKind.OPTIMIZE, candidate_id=None)
    with pytest.raises(TaskError):
        _task(TaskKind.OPTIMIZE, skill_ref=_skill())
    with pytest.raises(TaskError):
        _task(TaskKind.TEST, skill_ref=None)
    with pytest.raises(TaskError):
        _task(TaskKind.PROFILE, candidate_id=None)


def test_task_text_fields_are_required() -> None:
    with pytest.raises(TaskError):
        _task(objective="")
    with pytest.raises(TaskError):
        _task(context_ref="")
    with pytest.raises(TaskError):
        _task(budget_ref="")
    with pytest.raises(TaskError):
        _task(constraints=("",))
    task_id = TaskId.generate()
    with pytest.raises(TaskError):
        _task(id=task_id, retry_of_task_id=task_id)


# ---- lifecycle --------------------------------------------------------------
def test_task_success() -> None:
    task = _task(TaskKind.TEST)
    task.start()

    task.succeed("artifact://result", 100)

    assert task.state is TaskState.SUCCEEDED
    assert task.result_ref == "artifact://result"
    assert task.finished_at == 100
    assert task.terminal_reason is None


def test_task_cancel_and_interrupt_from_assigned() -> None:
    cancelled = _task(TaskKind.GENERATE)
    cancelled.cancel("user stop", 100)
    assert cancelled.state is TaskState.CANCELLED
    assert cancelled.terminal_reason == "user stop"
    assert cancelled.finished_at == 100

    interrupted = _task(TaskKind.GENERATE)
    interrupted.interrupt("control restart", 200)
    assert interrupted.state is TaskState.INTERRUPTED
    assert interrupted.terminal_reason == "control restart"
    assert interrupted.finished_at == 200


def test_task_failure_from_running() -> None:
    task = _task(TaskKind.OPTIMIZE)
    task.start()
    task.fail("compile error", 300)

    assert task.state is TaskState.FAILED
    assert task.terminal_reason == "compile error"
    assert task.finished_at == 300


# ---- guards -----------------------------------------------------------------
def test_terminal_task_rejects_transitions() -> None:
    task = _task(TaskKind.TEST)
    task.start()
    task.succeed("artifact://result", 100)

    with pytest.raises(TaskError):
        task.start()
    with pytest.raises(TaskError):
        task.succeed("other", 200)
    with pytest.raises(TaskError):
        task.fail("late", 200)
    with pytest.raises(TaskError):
        task.cancel("late", 200)
    with pytest.raises(TaskError):
        task.interrupt("late", 200)


def test_invalid_task_transitions() -> None:
    task = _task(TaskKind.TEST)

    with pytest.raises(TaskError):
        task.succeed("artifact://result", 100)
    with pytest.raises(TaskError):
        task.fail("no start", 100)
    with pytest.raises(TaskError):
        task.cancel("", 100)

    task.start()
    with pytest.raises(TaskError):
        task.start()
    with pytest.raises(TaskError):
        task.succeed("", 100)


def test_terminal_constructor_fields_are_consistent() -> None:
    with pytest.raises(TaskError):
        _task(TaskKind.TEST, state=TaskState.SUCCEEDED)
    with pytest.raises(TaskError):
        _task(TaskKind.TEST, state=TaskState.FAILED, finished_at=10)
    with pytest.raises(TaskError):
        _task(TaskKind.TEST, state=TaskState.RUNNING, finished_at=10)
    with pytest.raises(TaskError):
        _task(TaskKind.TEST, state=TaskState.ASSIGNED, result_ref="artifact://result")


def test_retry_uses_a_new_task_id() -> None:
    original = _task(TaskKind.OPTIMIZE)
    retry = _task(TaskKind.OPTIMIZE, retry_of_task_id=original.id)

    assert retry.id != original.id
    assert retry.retry_of_task_id == original.id

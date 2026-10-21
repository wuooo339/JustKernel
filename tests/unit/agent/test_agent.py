from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.errors import AgentError
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import WORKER_ROLES, AgentState, Role
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, ClusterId, TaskId


# ---- helpers ----------------------------------------------------------------
def _skill() -> SkillRef:
    return SkillRef(
        name="optimizer",
        version="1",
        source_path="/skills/base/optimizer",
        digest=Digest.from_text("skill"),
    )


def _worker(role: Role = Role.OPTIMIZER, **overrides: object) -> AgentInstance:
    values: dict[str, object] = {
        "id": AgentId.generate(),
        "cluster_id": ClusterId.generate(),
        "role": role,
        "mentor_id": AgentId.generate(),
        "model_profile": "model-1",
        "skills": (_skill(),),
        "created_at": 0,
    }
    values.update(overrides)
    return AgentInstance(**values)


def _supervisor(**overrides: object) -> AgentInstance:
    values: dict[str, object] = {
        "id": AgentId.generate(),
        "cluster_id": ClusterId.generate(),
        "role": Role.SUPERVISOR,
        "mentor_id": None,
        "model_profile": "model-1",
        "skills": (_skill(),),
        "created_at": 0,
    }
    values.update(overrides)
    return AgentInstance(**values)


# ---- role and skill validation ---------------------------------------------
def test_worker_roles_require_a_mentor() -> None:
    for role in WORKER_ROLES:
        assert _worker(role).mentor_id is not None

    with pytest.raises(AgentError):
        _worker(Role.OPTIMIZER, mentor_id=None)


def test_non_worker_roles_reject_a_mentor() -> None:
    with pytest.raises(AgentError):
        _supervisor(mentor_id=AgentId.generate())


def test_skill_ref_requires_fields() -> None:
    assert _skill().name == "optimizer"

    for field in ("name", "version", "source_path"):
        values = {
            "name": "optimizer",
            "version": "1",
            "source_path": "/skills/base/optimizer",
            "digest": Digest.from_text("skill"),
        }
        values[field] = ""
        with pytest.raises(AgentError):
            SkillRef(**values)


# ---- lifecycle --------------------------------------------------------------
def test_agent_lifecycle_with_task() -> None:
    agent = _worker()
    task = TaskId.generate()

    assert agent.state is AgentState.CREATED
    agent.initialize()
    assert agent.state is AgentState.IDLE

    agent.start_task(task)
    assert agent.state is AgentState.RUNNING
    assert agent.current_task_id == task

    agent.complete_task()
    assert agent.state is AgentState.IDLE
    assert agent.current_task_id is None

    agent.close(100)
    assert agent.state is AgentState.CLOSED
    assert agent.closed_at == 100


def test_agent_turn_without_task() -> None:
    agent = _supervisor()
    agent.initialize()
    agent.start_turn()

    assert agent.state is AgentState.RUNNING
    assert agent.current_task_id is None

    agent.finish_turn()
    assert agent.state is AgentState.IDLE


def test_agent_interrupt_and_resume_with_new_session() -> None:
    agent = _worker()
    agent.initialize()
    agent.start_task(TaskId.generate())

    agent.interrupt()
    assert agent.state is AgentState.INTERRUPTED
    assert agent.current_task_id is None

    agent.resume("session-2")
    assert agent.state is AgentState.IDLE
    assert agent.session_id == "session-2"


def test_agent_fail_and_close() -> None:
    agent = _worker()
    agent.initialize()
    agent.start_turn()
    agent.fail()

    assert agent.state is AgentState.FAILED
    agent.close(200)
    assert agent.state is AgentState.CLOSED


# ---- guards -----------------------------------------------------------------
def test_invalid_agent_transitions() -> None:
    created = _worker()
    for action in (
        created.start_turn,
        created.complete_task,
        created.interrupt,
        created.fail,
    ):
        with pytest.raises(AgentError):
            action()
    with pytest.raises(AgentError):
        created.resume("session")
    with pytest.raises(AgentError):
        created.close(100)

    created.initialize()
    with pytest.raises(AgentError):
        created.initialize()

    created.start_turn()
    with pytest.raises(AgentError):
        created.start_turn()
    with pytest.raises(AgentError):
        created.start_task(TaskId.generate())
    with pytest.raises(AgentError):
        created.close(100)

    created.finish_turn()
    with pytest.raises(AgentError):
        created.resume("session")


def test_closed_agent_rejects_new_work() -> None:
    agent = _worker()
    agent.initialize()
    agent.close(100)

    with pytest.raises(AgentError):
        agent.start_turn()
    with pytest.raises(AgentError):
        agent.start_task(TaskId.generate())
    with pytest.raises(AgentError):
        agent.close(200)


def test_terminal_and_running_fields_are_validated() -> None:
    with pytest.raises(AgentError):
        _worker(state=AgentState.CLOSED)
    with pytest.raises(AgentError):
        _worker(state=AgentState.IDLE, closed_at=10)
    with pytest.raises(AgentError):
        _worker(state=AgentState.IDLE, current_task_id=TaskId.generate())
    with pytest.raises(AgentError):
        _worker(model_profile="")

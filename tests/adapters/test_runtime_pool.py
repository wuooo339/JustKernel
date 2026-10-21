from __future__ import annotations

from pathlib import Path

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.platform.runtime.checkpoint import CheckpointStore
from justkernel.platform.runtime.errors import RuntimeLimitError, RuntimeStateError
from justkernel.platform.runtime.pool import AgentRuntimePool
from justkernel.platform.runtime.runner import AgentRunRequest, RunnerResult
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, ClusterId


# ---- fake runner ------------------------------------------------------------
class FakeRunner:
    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []
        self.callback = None

    def run(self, request: AgentRunRequest) -> RunnerResult:
        self.requests.append(request)
        if self.callback is not None:
            self.callback(request)
        return RunnerResult(
            output=f"output:{request.input}",
            checkpoint={"step": len(self.requests), "input": request.input},
        )


def _skill() -> SkillRef:
    return SkillRef(
        name="mentor",
        version="1",
        source_path="/skills/base/mentor",
        digest=Digest.from_text("skill"),
    )


def _pool(
    tmp_path: Path,
    *,
    max_agents: int = 4,
    runtime_processes: int = 2,
    model_concurrency: int = 2,
) -> tuple[AgentRuntimePool, FakeRunner, CheckpointStore]:
    runner = FakeRunner()
    checkpoints = CheckpointStore(tmp_path / "checkpoints")
    pool = AgentRuntimePool(
        runner,
        checkpoints,
        max_agents=max_agents,
        runtime_processes=runtime_processes,
        model_concurrency=model_concurrency,
    )
    return pool, runner, checkpoints


def _create(
    pool: AgentRuntimePool,
    *,
    agent_id: AgentId | None = None,
    cluster_id: ClusterId | None = None,
    role: Role = Role.MENTOR,
) -> object:
    return pool.create_agent(
        agent_id=agent_id or AgentId.generate(),
        cluster_id=cluster_id or ClusterId.generate(),
        role=role,
        model_profile="model-1",
        skills=(_skill(),),
    )


# ---- pool -------------------------------------------------------------------
def test_agent_pool_processes_and_limits(tmp_path: Path) -> None:
    pool, _, _ = _pool(tmp_path, max_agents=3, runtime_processes=2)
    cluster = ClusterId.generate()

    first = _create(pool, cluster_id=cluster)
    second = _create(pool, cluster_id=cluster)
    third = _create(pool, cluster_id=cluster)

    assert [first.process_index, second.process_index, third.process_index] == [0, 1, 0]
    assert pool.active_count == 3
    with pytest.raises(RuntimeLimitError):
        _create(pool, cluster_id=cluster)

    pool.close_agent(first.agent_id)
    replacement = _create(pool, cluster_id=cluster)
    assert replacement.process_index == 0


def test_single_turn_and_checkpoint_round_trip(tmp_path: Path) -> None:
    pool, runner, checkpoints = _pool(tmp_path, model_concurrency=2)
    agent = _create(pool)

    result = pool.start_turn(agent.agent_id, "first")

    assert result.output == "output:first"
    assert agent.state is AgentState.IDLE
    assert agent.current_turn_id is None
    assert len(runner.requests) == 1
    assert checkpoints.load(agent.cluster_id, agent.agent_id, agent.session_id) == {
        "step": 1,
        "input": "first",
    }

    pool.start_turn(agent.agent_id, "second")
    assert runner.requests[1].checkpoint == {"step": 1, "input": "first"}


def test_second_turn_is_rejected_while_running(tmp_path: Path) -> None:
    pool, runner, _ = _pool(tmp_path, model_concurrency=2)
    agent = _create(pool)
    errors: list[Exception] = []

    def callback(request: AgentRunRequest) -> None:
        if request.agent_id == agent.agent_id:
            try:
                pool.start_turn(agent.agent_id, "nested")
            except RuntimeStateError as error:
                errors.append(error)

    runner.callback = callback
    pool.start_turn(agent.agent_id, "outer")

    assert errors
    assert agent.state is AgentState.IDLE


def test_model_concurrency_limit(tmp_path: Path) -> None:
    pool, runner, _ = _pool(tmp_path, model_concurrency=1)
    first = _create(pool)
    second = _create(pool)
    errors: list[Exception] = []

    def callback(request: AgentRunRequest) -> None:
        if request.agent_id == first.agent_id:
            try:
                pool.start_turn(second.agent_id, "nested")
            except RuntimeLimitError as error:
                errors.append(error)

    runner.callback = callback
    pool.start_turn(first.agent_id, "outer")

    assert errors


def test_interrupt_and_resume_use_new_session(tmp_path: Path) -> None:
    pool, runner, checkpoints = _pool(tmp_path, model_concurrency=2)
    agent = _create(pool)
    original_session = agent.session_id

    def callback(request: AgentRunRequest) -> None:
        if request.agent_id == agent.agent_id and request.session_id == agent.session_id:
            pool.interrupt(agent.agent_id)

    runner.callback = callback
    pool.start_turn(agent.agent_id, "first")

    assert agent.state is AgentState.INTERRUPTED
    with pytest.raises(RuntimeStateError):
        pool.start_turn(agent.agent_id, "retry")

    resumed = pool.resume(agent.agent_id, "new-session")
    assert resumed.state is AgentState.IDLE
    assert resumed.session_id == "new-session"

    runner.callback = None
    pool.start_turn(agent.agent_id, "second")
    assert runner.requests[-1].session_id == "new-session"
    assert len(runner.requests) == 2
    assert checkpoints.list_sessions(agent.cluster_id, agent.agent_id) == (
        "new-session",
        original_session,
    )


def test_closed_agent_rejects_turns(tmp_path: Path) -> None:
    pool, _, _ = _pool(tmp_path)
    agent = _create(pool)

    pool.close_agent(agent.agent_id)
    with pytest.raises(RuntimeStateError):
        pool.start_turn(agent.agent_id, "late")


# ---- checkpoints ------------------------------------------------------------
def test_checkpoint_store_missing_and_listing(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "checkpoints")
    cluster = ClusterId.generate()
    agent = AgentId.generate()

    assert store.load(cluster, agent, "session-1") is None
    ref = store.save(cluster, agent, "session-1", {"value": 1})
    assert store.load(cluster, agent, "session-1") == {"value": 1}
    assert store.list_sessions(cluster, agent) == ("session-1",)
    assert Path(ref).name == "session-1.json"

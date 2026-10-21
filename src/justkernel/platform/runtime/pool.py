"""Logical agent runtime pool."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.platform.runtime.checkpoint import CheckpointStore
from justkernel.platform.runtime.errors import RuntimeLimitError, RuntimeStateError
from justkernel.platform.runtime.runner import AgentRunner, AgentRunRequest, RunnerResult
from justkernel.shared.ids import AgentId, ClusterId


# ---- RuntimeSession ---------------------------------------------------------
@dataclass(slots=True)
class RuntimeSession:
    agent_id: AgentId
    cluster_id: ClusterId
    role: Role
    model_profile: str
    skills: tuple[SkillRef, ...]
    mentor_id: AgentId | None
    session_id: str
    process_index: int
    state: AgentState = AgentState.IDLE
    current_turn_id: str | None = None
    checkpoint_ref: str | None = None


# ---- AgentRuntimePool -------------------------------------------------------
class AgentRuntimePool:
    def __init__(
        self,
        runner: AgentRunner,
        checkpoints: CheckpointStore,
        *,
        max_agents: int = 100,
        runtime_processes: int = 8,
        model_concurrency: int = 8,
    ) -> None:
        if max_agents < 1 or runtime_processes < 1 or model_concurrency < 1:
            raise RuntimeLimitError("runtime limits must be positive")
        self.runner = runner
        self.checkpoints = checkpoints
        self.max_agents = max_agents
        self.runtime_processes = runtime_processes
        self.model_concurrency = model_concurrency
        self._sessions: dict[AgentId, RuntimeSession] = {}
        self._by_process: dict[int, set[AgentId]] = {
            index: set() for index in range(runtime_processes)
        }
        self._active_turns = 0
        self._turn_counter = 0
        self._session_counter = 0

    @property
    def active_count(self) -> int:
        return sum(
            1 for session in self._sessions.values() if session.state is not AgentState.CLOSED
        )

    def create_agent(
        self,
        *,
        agent_id: AgentId,
        cluster_id: ClusterId,
        role: Role,
        model_profile: str,
        skills: tuple[SkillRef, ...],
        mentor_id: AgentId | None = None,
    ) -> RuntimeSession:
        if agent_id in self._sessions:
            raise RuntimeStateError(f"agent already exists: {agent_id}")
        if self.active_count >= self.max_agents:
            raise RuntimeLimitError("agent limit reached")
        process_index = self._least_loaded_process()
        self._session_counter += 1
        session = RuntimeSession(
            agent_id=agent_id,
            cluster_id=cluster_id,
            role=role,
            model_profile=model_profile,
            skills=skills,
            mentor_id=mentor_id,
            session_id=f"session-{self._session_counter}",
            process_index=process_index,
        )
        self._sessions[agent_id] = session
        self._by_process[process_index].add(agent_id)
        return session

    def start_turn(self, agent_id: AgentId, input: str) -> RunnerResult:
        session = self.get(agent_id)
        request = self._begin_turn(session, input)
        try:
            result = self.runner.run(request)
            session.checkpoint_ref = self.checkpoints.save(
                session.cluster_id,
                agent_id,
                session.session_id,
                result.checkpoint or {"output": result.output},
            )
        except BaseException:
            session.state = AgentState.FAILED
            session.current_turn_id = None
            raise
        finally:
            self._active_turns -= 1
        if session.state is AgentState.RUNNING:
            session.state = AgentState.IDLE
            session.current_turn_id = None
        return result

    def _begin_turn(self, session: RuntimeSession, input: str) -> AgentRunRequest:
        if session.state is not AgentState.IDLE:
            raise RuntimeStateError(f"agent is not idle: {session.state}")
        if self._active_turns >= self.model_concurrency:
            raise RuntimeLimitError("model concurrency limit reached")
        checkpoint = self.checkpoints.load(session.cluster_id, session.agent_id, session.session_id)
        self._turn_counter += 1
        session.current_turn_id = f"turn-{self._turn_counter}"
        session.state = AgentState.RUNNING
        self._active_turns += 1
        return AgentRunRequest(
            agent_id=session.agent_id,
            cluster_id=session.cluster_id,
            role=session.role,
            model_profile=session.model_profile,
            skills=session.skills,
            session_id=session.session_id,
            input=input,
            mentor_id=session.mentor_id,
            checkpoint=checkpoint,
        )

    def interrupt(self, agent_id: AgentId, reason: str = "interrupted") -> RuntimeSession:
        session = self.get(agent_id)
        if session.state is AgentState.RUNNING:
            session.state = AgentState.INTERRUPTED
            session.current_turn_id = None
        return session

    def interrupt_all(self, reason: str = "control restart") -> int:
        count = 0
        for session in self._sessions.values():
            if session.state is AgentState.RUNNING:
                session.state = AgentState.INTERRUPTED
                session.current_turn_id = None
                count += 1
        return count

    def resume(self, agent_id: AgentId, session_id: str) -> RuntimeSession:
        session = self.get(agent_id)
        if session.state is not AgentState.INTERRUPTED:
            raise RuntimeStateError(f"agent is not interrupted: {session.state}")
        if not session_id:
            raise RuntimeStateError("resume requires a new session id")
        session.session_id = session_id
        session.state = AgentState.IDLE
        session.current_turn_id = None
        return session

    def close_agent(self, agent_id: AgentId) -> RuntimeSession:
        session = self.get(agent_id)
        if session.state is AgentState.RUNNING:
            raise RuntimeStateError("cannot close a running agent")
        if session.state is AgentState.CLOSED:
            raise RuntimeStateError("agent is already closed")
        session.state = AgentState.CLOSED
        session.current_turn_id = None
        self._by_process[session.process_index].discard(agent_id)
        return session

    def get(self, agent_id: AgentId) -> RuntimeSession:
        session = self._sessions.get(agent_id)
        if session is None:
            raise RuntimeStateError(f"unknown agent: {agent_id}")
        return session

    def _least_loaded_process(self) -> int:
        return min(self._by_process, key=lambda index: len(self._by_process[index]))

"""Worker close flow with lease cleanup."""

from __future__ import annotations

from justkernel.agent.agent import AgentInstance
from justkernel.agent.errors import AgentError
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.lease_book import AgentLeaseBook
from justkernel.shared.ids import AgentId


# ---- WorkerLifecycle --------------------------------------------------------
class WorkerLifecycle:
    def __init__(self, agents: AgentService, leases: AgentLeaseBook) -> None:
        self.agents = agents
        self.leases = leases

    def close_worker(
        self,
        *,
        mentor_id: AgentId,
        worker_id: AgentId,
        now_ms: int,
    ) -> AgentInstance:
        worker = self._closable_worker(mentor_id, worker_id)
        self.leases.release_agent(worker.id, now_ms)
        return self.agents.close_worker(
            mentor_id=mentor_id,
            worker_id=worker_id,
            now_ms=now_ms,
        )

    def _closable_worker(self, mentor_id: AgentId, worker_id: AgentId) -> AgentInstance:
        mentor = self.agents.get_agent(mentor_id)
        worker = self.agents.get_agent(worker_id)
        if mentor.role is not Role.MENTOR:
            raise AgentError("only a mentor can close a worker")
        if worker.mentor_id != mentor_id:
            raise AgentError("worker does not belong to this mentor")
        if worker.state is AgentState.CLOSED:
            raise AgentError("worker is already closed")
        if worker.state is AgentState.RUNNING or worker.current_task_id is not None:
            raise AgentError("cancel or complete the worker task before closing")
        return worker

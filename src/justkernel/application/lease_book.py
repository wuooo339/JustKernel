"""Device-lease ownership book used during agent teardown."""

from __future__ import annotations

from justkernel.application.ports import HardwareQueuePort
from justkernel.shared.ids import AgentId, LeaseId, TaskId
from justkernel.testing.errors import LeaseError


# ---- AgentLeaseBook ---------------------------------------------------------
class AgentLeaseBook:
    def __init__(self, queue: HardwareQueuePort) -> None:
        self.queue = queue
        self._owners: dict[LeaseId, AgentId] = {}

    def acquire(
        self,
        *,
        agent_id: AgentId,
        task_id: TaskId,
        device: str,
        ttl_ms: int,
        now_ms: int,
    ) -> LeaseId:
        lease_id = self.queue.acquire(task_id, device, ttl_ms, now_ms)
        self._owners[lease_id] = agent_id
        return lease_id

    def release(self, lease_id: LeaseId, now_ms: int) -> None:
        if lease_id not in self._owners:
            raise LeaseError(f"lease is not tracked: {lease_id.value}")
        self.queue.release(lease_id, now_ms)
        del self._owners[lease_id]

    def release_agent(self, agent_id: AgentId, now_ms: int) -> int:
        leases = [lease for lease, owner in self._owners.items() if owner == agent_id]
        for lease_id in leases:
            self.release(lease_id, now_ms)
        return len(leases)

    def release_all(self, now_ms: int) -> int:
        leases = tuple(self._owners)
        for lease_id in leases:
            self.release(lease_id, now_ms)
        return len(leases)

    def leases_for(self, agent_id: AgentId) -> tuple[LeaseId, ...]:
        return tuple(lease for lease, owner in self._owners.items() if owner == agent_id)

    @property
    def active_count(self) -> int:
        return len(self._owners)

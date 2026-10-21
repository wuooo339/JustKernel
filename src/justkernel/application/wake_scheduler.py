"""Deterministic per-agent wake scheduler."""

from __future__ import annotations

from justkernel.comm.wake import WakeError, WakePolicy, WakeRequest, WakeWait
from justkernel.shared.events import DomainEvent
from justkernel.shared.ids import AgentId, EventId, WakeId


# ---- WakeScheduler ----------------------------------------------------------
class WakeScheduler:
    def __init__(self, policy: WakePolicy) -> None:
        self.policy = policy
        self._seen: set[tuple[AgentId, EventId]] = set()
        self._pending: dict[AgentId, WakeRequest] = {}
        self._claimed: dict[AgentId, WakeRequest] = {}
        self._waits: dict[AgentId, WakeWait] = {}
        self._running: set[AgentId] = set()

    def notify(
        self,
        agent_id: AgentId,
        event: DomainEvent,
        *,
        reason: str = "event",
        agent_version: int = 0,
        now_ms: int,
    ) -> bool:
        key = (agent_id, event.id)
        if key in self._seen:
            return False
        if agent_version < 0 or now_ms < 0:
            raise WakeError("notification time/version must be non-negative")
        self._seen.add(key)
        self._waits.pop(agent_id, None)
        previous = self._pending.get(agent_id)
        event_ids = (previous.event_ids if previous else ()) + (event.id,)
        not_before = now_ms + self.policy.wake_debounce_ms
        expected = previous.expected_agent_version if previous else agent_version
        wake = WakeRequest(
            id=previous.id if previous else WakeId.generate(),
            agent_id=agent_id,
            reason=previous.reason if previous else reason,
            event_ids=event_ids,
            expected_agent_version=expected,
            not_before=max(previous.not_before, not_before) if previous else not_before,
        )
        self._pending[agent_id] = wake
        return True

    def claim(
        self,
        agent_id: AgentId,
        *,
        agent_version: int,
        now_ms: int,
    ) -> WakeRequest | None:
        if agent_id in self._running:
            raise WakeError("agent already has a running turn")
        wake = self._pending.get(agent_id)
        if wake is None or now_ms < wake.not_before:
            return None
        del self._pending[agent_id]
        if agent_version != wake.expected_agent_version:
            raise WakeError("wake was created for a stale agent version")
        claimed = wake.claim()
        self._claimed[agent_id] = claimed
        self._running.add(agent_id)
        return claimed

    def complete(self, agent_id: AgentId, *, now_ms: int) -> WakeRequest:
        wake = self._claimed.pop(agent_id, None)
        if wake is None:
            raise WakeError("agent has no claimed turn")
        self._running.discard(agent_id)
        completed = wake.complete()
        wait = self._waits.pop(agent_id, None)
        if wait is not None and agent_id not in self._pending:
            self._pending[agent_id] = WakeRequest(
                id=WakeId.generate(),
                agent_id=agent_id,
                reason=f"wait:{wait.reason}",
                event_ids=wait.event_ids,
                expected_agent_version=wake.expected_agent_version,
                not_before=wait.deadline_ms,
            )
        return completed

    def fail(self, agent_id: AgentId, *, now_ms: int) -> WakeRequest:
        wake = self._claimed.pop(agent_id, None)
        if wake is None:
            raise WakeError("agent has no claimed turn")
        self._running.discard(agent_id)
        self._waits.pop(agent_id, None)
        return wake.fail()

    def wait(
        self,
        agent_id: AgentId,
        *,
        reason: str,
        deadline_ms: int,
        now_ms: int,
        event_ids: tuple[EventId, ...] = (),
    ) -> WakeWait:
        if agent_id not in self._running:
            raise WakeError("wait requires a running turn")
        wait = WakeWait(
            agent_id=agent_id,
            reason=reason,
            event_ids=event_ids,
            deadline_ms=deadline_ms,
            created_at=now_ms,
        )
        self._waits[agent_id] = wait
        return wait

    def is_running(self, agent_id: AgentId) -> bool:
        return agent_id in self._running

    def pending(self, agent_id: AgentId) -> WakeRequest | None:
        return self._pending.get(agent_id)

    def claimed(self, agent_id: AgentId) -> WakeRequest | None:
        return self._claimed.get(agent_id)

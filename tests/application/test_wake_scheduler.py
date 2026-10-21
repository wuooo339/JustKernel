from __future__ import annotations

import pytest

from justkernel.application.wake_scheduler import WakeScheduler
from justkernel.comm.wake import WakeError, WakePolicy
from justkernel.shared.events import DomainEvent, EventType
from justkernel.shared.ids import AgentId, ClusterId, EventId
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _event(*, at: int = 0) -> DomainEvent:
    return DomainEvent(
        id=EventId.generate(),
        cluster_id=ClusterId.generate(),
        type=EventType.TASK_ASSIGNED,
        event_version=1,
        aggregate_type="task",
        aggregate_id="task-1",
        aggregate_version=0,
        actor=Principal.system(),
        occurred_at=at,
    )


def _scheduler() -> WakeScheduler:
    return WakeScheduler(
        WakePolicy(
            wake_debounce_ms=100,
            summary_interval_s=30,
            wait_deadline_s=300,
            stalled_timeout_s=60,
            max_stalled_wakes=1,
        )
    )


# ---- inbox/debounce ---------------------------------------------------------
def test_duplicate_events_are_ignored_and_debounce_merges() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()
    first = _event()
    second = _event(at=20)

    assert scheduler.notify(agent, first, agent_version=1, now_ms=0) is True
    assert scheduler.notify(agent, first, agent_version=1, now_ms=5) is False
    assert scheduler.notify(agent, second, agent_version=1, now_ms=20) is True

    pending = scheduler.pending(agent)
    assert pending is not None
    assert pending.event_ids == (first.id, second.id)
    assert scheduler.claim(agent, agent_version=1, now_ms=100) is None

    claimed = scheduler.claim(agent, agent_version=1, now_ms=120)
    assert claimed is not None
    assert claimed.event_ids == (first.id, second.id)
    assert scheduler.is_running(agent)


# ---- single turn ------------------------------------------------------------
def test_only_one_turn_can_run_per_agent() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()
    scheduler.notify(agent, _event(), agent_version=1, now_ms=0)
    claimed = scheduler.claim(agent, agent_version=1, now_ms=100)
    assert claimed is not None

    with pytest.raises(WakeError):
        scheduler.claim(agent, agent_version=1, now_ms=101)
    scheduler.complete(agent, now_ms=110)
    assert scheduler.is_running(agent) is False
    assert scheduler.claim(agent, agent_version=1, now_ms=120) is None


def test_events_arriving_during_turn_stay_pending() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()
    scheduler.notify(agent, _event(), agent_version=1, now_ms=0)
    scheduler.claim(agent, agent_version=1, now_ms=100)
    second = _event(at=150)
    assert scheduler.notify(agent, second, agent_version=1, now_ms=150) is True

    scheduler.complete(agent, now_ms=160)
    assert scheduler.pending(agent) is not None
    assert scheduler.claim(agent, agent_version=1, now_ms=249) is None
    claimed = scheduler.claim(agent, agent_version=1, now_ms=250)
    assert claimed is not None
    assert claimed.event_ids == (second.id,)


# ---- WAIT -------------------------------------------------------------------
def test_wait_deadline_wakes_exactly_once() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()
    scheduler.notify(agent, _event(), agent_version=1, now_ms=0)
    scheduler.claim(agent, agent_version=1, now_ms=100)
    scheduler.wait(agent, reason="hardware result", deadline_ms=500, now_ms=100)
    scheduler.complete(agent, now_ms=110)

    assert scheduler.claim(agent, agent_version=1, now_ms=499) is None
    wake = scheduler.claim(agent, agent_version=1, now_ms=500)
    assert wake is not None
    assert wake.reason == "wait:hardware result"
    scheduler.complete(agent, now_ms=510)
    assert scheduler.claim(agent, agent_version=1, now_ms=600) is None


def test_event_satisfies_wait_before_deadline() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()
    scheduler.notify(agent, _event(), agent_version=1, now_ms=0)
    scheduler.claim(agent, agent_version=1, now_ms=100)
    scheduler.wait(agent, reason="result", deadline_ms=500, now_ms=100)
    result_event = _event(at=200)
    assert scheduler.notify(agent, result_event, agent_version=1, now_ms=200) is True
    scheduler.complete(agent, now_ms=210)

    wake = scheduler.claim(agent, agent_version=1, now_ms=300)
    assert wake is not None
    assert wake.event_ids == (result_event.id,)
    assert not wake.reason.startswith("wait:")


def test_wait_requires_running_turn_and_future_deadline() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()

    with pytest.raises(WakeError):
        scheduler.wait(agent, reason="result", deadline_ms=100, now_ms=0)

    scheduler.notify(agent, _event(), agent_version=1, now_ms=0)
    scheduler.claim(agent, agent_version=1, now_ms=100)
    with pytest.raises(WakeError):
        scheduler.wait(agent, reason="result", deadline_ms=100, now_ms=100)


# ---- stale version ----------------------------------------------------------
def test_stale_agent_version_cannot_claim() -> None:
    scheduler = _scheduler()
    agent = AgentId.generate()
    scheduler.notify(agent, _event(), agent_version=1, now_ms=0)

    with pytest.raises(WakeError):
        scheduler.claim(agent, agent_version=2, now_ms=100)
    assert scheduler.pending(agent) is None
    assert scheduler.claim(agent, agent_version=2, now_ms=101) is None

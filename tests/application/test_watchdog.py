from __future__ import annotations

import pytest

from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import FakeIds, InMemoryClusterRepository
from justkernel.application.watchdog_service import (
    ClusterActivity,
    WatchdogAction,
    WatchdogService,
)
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import ClusterState, StartMode
from justkernel.comm.wake import WakePolicy
from justkernel.shared.digest import Digest
from justkernel.shared.events import EventType
from justkernel.shared.ids import AgentId


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _stack() -> tuple[WatchdogService, ClusterService, object]:
    repository = InMemoryClusterRepository()
    service = ClusterService(repository, FakeIds())
    cluster = service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    service.start_cluster(cluster.id)
    watchdog = WatchdogService(
        service,
        WakePolicy(
            wake_debounce_ms=100,
            summary_interval_s=30,
            wait_deadline_s=300,
            stalled_timeout_s=60,
            max_stalled_wakes=1,
        ),
    )
    return watchdog, service, cluster


def _activity(**overrides: int) -> ClusterActivity:
    values = {
        "active_tasks": 0,
        "active_turns": 0,
        "pending_wakes": 0,
        "valid_waits": 0,
    }
    values.update(overrides)
    return ClusterActivity(**values)


# ---- stall detection --------------------------------------------------------
def test_idle_cluster_wakes_supervisor_once() -> None:
    watchdog, _, cluster = _stack()

    result = watchdog.check(cluster.id, activity=_activity(), now_ms=100)

    assert result.action is WatchdogAction.WOKE_SUPERVISOR
    assert result.event_type is EventType.CLUSTER_STALLED
    assert result.stall_count == 1
    assert result.cluster.state is ClusterState.RUNNING


def test_valid_wait_and_pending_work_are_not_stalled() -> None:
    watchdog, _, cluster = _stack()

    for activity in (
        _activity(valid_waits=1),
        _activity(pending_wakes=1),
        _activity(active_tasks=1),
        _activity(active_turns=1),
    ):
        result = watchdog.check(cluster.id, activity=activity, now_ms=100)
        assert result.action is WatchdogAction.NONE
        assert result.stall_count == 0


def test_repeated_stall_pauses_cluster() -> None:
    watchdog, _, cluster = _stack()

    first = watchdog.check(cluster.id, activity=_activity(), now_ms=100)
    second = watchdog.check(cluster.id, activity=_activity(), now_ms=200)

    assert first.action is WatchdogAction.WOKE_SUPERVISOR
    assert second.action is WatchdogAction.PAUSED
    assert second.event_type is EventType.CLUSTER_STALLED
    assert second.cluster.state is ClusterState.PAUSED
    assert second.stall_count == 2


def test_activity_resets_stall_counter() -> None:
    watchdog, _, cluster = _stack()
    watchdog.check(cluster.id, activity=_activity(), now_ms=100)
    watchdog.check(cluster.id, activity=_activity(active_tasks=1), now_ms=150)

    again = watchdog.check(cluster.id, activity=_activity(), now_ms=200)

    assert again.action is WatchdogAction.WOKE_SUPERVISOR
    assert again.stall_count == 1


def test_paused_cluster_is_ignored() -> None:
    watchdog, cluster_service, cluster = _stack()
    cluster_service.pause_cluster(cluster.id)

    result = watchdog.check(cluster.id, activity=_activity(), now_ms=100)

    assert result.action is WatchdogAction.NONE
    assert result.stall_count == 0
    assert result.cluster.state is ClusterState.PAUSED


def test_negative_activity_is_rejected() -> None:
    with pytest.raises(ValueError):
        _activity(active_tasks=-1)

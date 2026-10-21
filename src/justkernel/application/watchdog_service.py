"""Watchdog for stalled RUNNING clusters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from justkernel.application.cluster_service import ClusterService
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.state import ClusterState
from justkernel.comm.wake import WakePolicy
from justkernel.shared.events import EventType
from justkernel.shared.ids import ClusterId


# ---- WatchdogAction ---------------------------------------------------------
class WatchdogAction(StrEnum):
    NONE = "NONE"
    WOKE_SUPERVISOR = "WOKE_SUPERVISOR"
    PAUSED = "PAUSED"


# ---- ClusterActivity --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ClusterActivity:
    active_tasks: int = 0
    active_turns: int = 0
    pending_wakes: int = 0
    valid_waits: int = 0

    def __post_init__(self) -> None:
        for name in ("active_tasks", "active_turns", "pending_wakes", "valid_waits"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    @property
    def has_work(self) -> bool:
        return any((self.active_tasks, self.active_turns, self.pending_wakes, self.valid_waits))


# ---- WatchdogResult ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class WatchdogResult:
    cluster: Cluster
    action: WatchdogAction
    stall_count: int
    event_type: EventType | None = None


# ---- WatchdogService --------------------------------------------------------
class WatchdogService:
    def __init__(self, clusters: ClusterService, policy: WakePolicy) -> None:
        self.clusters = clusters
        self.policy = policy
        self._stalls: dict[ClusterId, int] = {}

    def check(
        self,
        cluster_id: ClusterId,
        *,
        activity: ClusterActivity,
        now_ms: int,
    ) -> WatchdogResult:
        cluster = self.clusters.get(cluster_id)
        if now_ms < cluster.created_at:
            raise ValueError("watchdog time precedes cluster creation")
        if cluster.state is not ClusterState.RUNNING:
            self._stalls.pop(cluster.id, None)
            return WatchdogResult(cluster, WatchdogAction.NONE, 0)
        if activity.has_work:
            self._stalls.pop(cluster.id, None)
            return WatchdogResult(cluster, WatchdogAction.NONE, 0)
        count = self._stalls.get(cluster.id, 0) + 1
        if count <= self.policy.max_stalled_wakes:
            self._stalls[cluster.id] = count
            return WatchdogResult(
                cluster,
                WatchdogAction.WOKE_SUPERVISOR,
                count,
                EventType.CLUSTER_STALLED,
            )
        paused = self.clusters.pause_cluster(cluster.id)
        self._stalls.pop(cluster.id, None)
        return WatchdogResult(
            paused,
            WatchdogAction.PAUSED,
            count,
            EventType.CLUSTER_STALLED,
        )

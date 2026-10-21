"""Dependency container for HTTP read routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from justkernel.application.cluster_service import ClusterService
from justkernel.application.ports import (
    AgentRepositoryPort,
    ArtifactStorePort,
    CandidateRepositoryPort,
    ClusterRepositoryPort,
    DirectionRepositoryPort,
    MessageBusPort,
    ReportRepositoryPort,
    TaskRepositoryPort,
    TestRecordRepositoryPort,
    ToolJobRepositoryPort,
)
from justkernel.application.start_cluster_service import ClusterStartService
from justkernel.platform.hardware.queue import HardwareQueue
from justkernel.platform.persistence.events import EventStore


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class ApiContext:
    clusters: ClusterRepositoryPort
    agents: AgentRepositoryPort
    tasks: TaskRepositoryPort
    candidates: CandidateRepositoryPort
    records: TestRecordRepositoryPort
    jobs: ToolJobRepositoryPort
    directions: DirectionRepositoryPort
    reports: ReportRepositoryPort
    messages: MessageBusPort
    artifacts: ArtifactStorePort | None = None
    hardware: HardwareQueue | None = None
    cluster_service: ClusterService | None = None
    start_cluster: ClusterStartService | None = None
    events: EventStore | None = None
    now_ms: Callable[[], int] = field(default=_now_ms)

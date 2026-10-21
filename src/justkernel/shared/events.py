"""Domain event types and envelope."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import ClusterId, EventId
from justkernel.shared.principal import Principal


# ---- EventType --------------------------------------------------------------
class EventType(StrEnum):
    CLUSTER_STARTED = "cluster.started"
    CLUSTER_CONVERGING = "cluster.converging"
    CLUSTER_COMPLETED = "cluster.completed"
    CLUSTER_STOPPED = "cluster.stopped"
    AGENT_CREATED = "agent.created"
    AGENT_IDLE = "agent.idle"
    AGENT_RUNNING = "agent.running"
    AGENT_FAILED = "agent.failed"
    AGENT_CLOSED = "agent.closed"
    DIRECTION_ASSIGNED = "direction.assigned"
    DIRECTION_PAUSED = "direction.paused"
    DIRECTION_COMPLETED = "direction.completed"
    TASK_ASSIGNED = "task.assigned"
    TASK_RUNNING = "task.running"
    TASK_SUCCEEDED = "task.succeeded"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    BOARD_POSTED = "board.posted"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_DUPLICATE = "message.duplicate"
    MESSAGE_REJECTED = "message.rejected"
    CANDIDATE_COMMITTED = "candidate.committed"
    CANDIDATE_DUPLICATE = "candidate.duplicate"
    CANDIDATE_EVALUATION_UPDATED = "candidate.evaluation.updated"
    BEST_NOMINATED = "best.nominated"
    BEST_VALIDATED = "best.validated"
    BEST_FAILED = "best.failed"
    BASELINE_ESTABLISHED = "baseline.established"
    TOOL_JOB_QUEUED = "tool_job.queued"
    TOOL_JOB_COMPLETED = "tool_job.completed"
    TOOL_JOB_FAILED = "tool_job.failed"
    TOOL_JOB_INTERRUPTED = "tool_job.interrupted"
    WAKE_PENDING = "wake.pending"
    WAKE_CLAIMED = "wake.claimed"
    WAKE_COMPLETED = "wake.completed"
    WAKE_FAILED = "wake.failed"
    CLUSTER_STALLED = "cluster.stalled"
    CLUSTER_RESUMED = "cluster.resumed"
    HARDWARE_QUEUED = "hardware.queued"
    HARDWARE_LEASED = "hardware.leased"
    HARDWARE_RELEASED = "hardware.released"
    HARDWARE_EXPIRED = "hardware.expired"
    REPORT_CREATED = "report.created"


# ---- EventError -------------------------------------------------------------
class EventError(JustKernelError):
    code = ErrorCode.INVALID_EVENT


# ---- DomainEvent ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class DomainEvent:
    id: EventId
    cluster_id: ClusterId
    type: EventType
    event_version: int
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    actor: Principal
    occurred_at: int
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.event_version < 1:
            raise EventError("event_version must be positive")
        if self.aggregate_version < 0:
            raise EventError("aggregate_version must be non-negative")
        if not self.aggregate_type or not self.aggregate_id:
            raise EventError("aggregate type and id must be non-empty")
        if self.occurred_at < 0:
            raise EventError("occurred_at must be non-negative")
        for name in ("correlation_id", "causation_id"):
            value = getattr(self, name)
            if value is not None and not value:
                raise EventError(f"{name} must be non-empty")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

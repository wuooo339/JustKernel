"""Message envelope and channel/type consistency."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from justkernel.comm.channels import Channel, ChannelKind
from justkernel.comm.errors import MessageError
from justkernel.shared.ids import ClusterId, MessageId
from justkernel.shared.principal import Principal


# ---- MessageType ------------------------------------------------------------
class MessageType(StrEnum):
    DIRECTION_ASSIGNED = "DirectionAssigned"
    MENTOR_SUMMARY = "MentorSummary"
    MENTOR_DATA_SHARED = "MentorDataShared"
    CONSULTANT_BRIEF = "ConsultantBrief"
    TASK_ASSIGNED = "TaskAssigned"
    WORKER_RESULT = "WorkerResult"
    CANDIDATE_COMMITTED = "CandidateCommitted"
    TEST_RECORD_CREATED = "TestRecordCreated"
    HARDWARE_QUEUE_EVENT = "HardwareQueueEvent"
    DECISION = "Decision"
    AGENT_LIFECYCLE = "AgentLifecycle"


MESSAGE_CHANNEL: dict[MessageType, ChannelKind] = {
    MessageType.DIRECTION_ASSIGNED: ChannelKind.MENTOR_BOARD,
    MessageType.MENTOR_SUMMARY: ChannelKind.MENTOR_BOARD,
    MessageType.MENTOR_DATA_SHARED: ChannelKind.MENTOR_BOARD,
    MessageType.DECISION: ChannelKind.MENTOR_BOARD,
    MessageType.CONSULTANT_BRIEF: ChannelKind.CONSULTANT_BOARD,
    MessageType.TASK_ASSIGNED: ChannelKind.WORKER,
    MessageType.WORKER_RESULT: ChannelKind.WORKER,
    MessageType.CANDIDATE_COMMITTED: ChannelKind.WORKER,
    MessageType.TEST_RECORD_CREATED: ChannelKind.WORKER,
    MessageType.HARDWARE_QUEUE_EVENT: ChannelKind.HARDWARE,
    MessageType.AGENT_LIFECYCLE: ChannelKind.CONTROL,
}

BOARD_CHANNELS = frozenset({ChannelKind.MENTOR_BOARD, ChannelKind.CONSULTANT_BOARD})


# ---- Message ----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Message:
    id: MessageId
    cluster_id: ClusterId
    seq: int
    channel: Channel
    type: MessageType
    sender: Principal
    created_at: int
    recipient: Principal | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seq < 1:
            raise MessageError("message seq must be positive")
        if self.created_at < 0:
            raise MessageError("created_at must be non-negative")
        expected = MESSAGE_CHANNEL.get(self.type)
        if expected is None or self.channel.kind is not expected:
            raise MessageError(f"{self.type} cannot use channel {self.channel.name}")
        if self.channel.kind in BOARD_CHANNELS and self.recipient is not None:
            raise MessageError("board messages must not have a recipient")
        if self.channel.kind is ChannelKind.WORKER and self.recipient is None:
            raise MessageError("worker messages require a recipient")
        for name in ("correlation_id", "causation_id"):
            value = getattr(self, name)
            if value is not None and not value:
                raise MessageError(f"{name} must be non-empty")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

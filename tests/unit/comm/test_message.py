from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from justkernel.comm.channels import Channel
from justkernel.comm.errors import MessageError
from justkernel.comm.message import Message, MessageType
from justkernel.shared.ids import AgentId, ClusterId, MessageId
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _message(**overrides: object) -> Message:
    values: dict[str, object] = {
        "id": MessageId.generate(),
        "cluster_id": ClusterId.generate(),
        "seq": 1,
        "channel": Channel.mentor_board(),
        "type": MessageType.DIRECTION_ASSIGNED,
        "sender": Principal.agent(AgentId.generate()),
        "created_at": 0,
        "payload": {"objective": "improve memory access"},
    }
    values.update(overrides)
    return Message(**values)


# ---- valid messages ---------------------------------------------------------
def test_board_message_and_immutable_payload() -> None:
    message = _message()

    assert message.recipient is None
    assert message.payload["objective"] == "improve memory access"

    with pytest.raises(TypeError):
        message.payload["objective"] = "changed"


def test_worker_message_requires_recipient() -> None:
    mentor = AgentId.generate()
    worker = AgentId.generate()
    message = _message(
        channel=Channel.worker(mentor, worker),
        type=MessageType.TASK_ASSIGNED,
        recipient=Principal.agent(worker),
    )

    assert message.channel.worker_id == worker


# ---- channel/type consistency ----------------------------------------------
def test_message_type_must_match_channel_kind() -> None:
    worker = AgentId.generate()
    with pytest.raises(MessageError):
        _message(channel=Channel.worker(AgentId.generate(), worker))
    with pytest.raises(MessageError):
        _message(
            channel=Channel.consultant_board(),
            type=MessageType.DIRECTION_ASSIGNED,
        )


def test_board_message_rejects_recipient() -> None:
    with pytest.raises(MessageError):
        _message(recipient=Principal.agent(AgentId.generate()))


def test_worker_message_rejects_missing_recipient() -> None:
    mentor = AgentId.generate()
    worker = AgentId.generate()
    with pytest.raises(MessageError):
        _message(
            channel=Channel.worker(mentor, worker),
            type=MessageType.WORKER_RESULT,
        )


# ---- envelope validation ----------------------------------------------------
def test_sequence_and_time_must_be_valid() -> None:
    with pytest.raises(MessageError):
        _message(seq=0)
    with pytest.raises(MessageError):
        _message(created_at=-1)


def test_message_is_frozen() -> None:
    message = _message()

    with pytest.raises(FrozenInstanceError):
        message.seq = 2

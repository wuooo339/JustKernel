from __future__ import annotations

from justkernel.comm.channels import Channel
from justkernel.comm.inbox import MessageInbox
from justkernel.comm.message import Message, MessageType
from justkernel.shared.ids import AgentId, ClusterId, MessageId
from justkernel.shared.principal import Principal


# ---- inbox ------------------------------------------------------------------
def test_duplicate_message_id_is_rejected() -> None:
    message = Message(
        id=MessageId.generate(),
        cluster_id=ClusterId.generate(),
        seq=1,
        channel=Channel.mentor_board(),
        type=MessageType.DIRECTION_ASSIGNED,
        sender=Principal.agent(AgentId.generate()),
        created_at=0,
        payload={"objective": "x"},
    )
    inbox = MessageInbox()

    assert inbox.accept(message) is True
    assert inbox.accept(message) is False
    assert len(inbox) == 1

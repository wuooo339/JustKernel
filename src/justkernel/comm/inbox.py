"""Message idempotency inbox."""

from __future__ import annotations

from dataclasses import dataclass, field

from justkernel.comm.message import Message
from justkernel.shared.ids import MessageId


# ---- MessageInbox -----------------------------------------------------------
@dataclass(slots=True)
class MessageInbox:
    _seen: set[MessageId] = field(default_factory=set)

    def accept(self, message: Message) -> bool:
        if message.id in self._seen:
            return False
        self._seen.add(message.id)
        return True

    def __len__(self) -> int:
        return len(self._seen)

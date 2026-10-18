"""Durable Judger/SOTA outbox, delivered and acknowledged through the A2A client."""

import asyncio
import hashlib
import json
import time
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter


# ---- Notice -----------------------------------------------------------------
class Notice(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    recipient: str
    topic: Literal["judge-feedback", "sota"]
    artifact: str
    message: str = Field(min_length=1, max_length=8000)
    state: Literal["pending", "delivered"] = "pending"
    attempts: int = 0
    next_at: float = 0
    error: str = ""


# ---- NoticeOutbox -----------------------------------------------------------
class NoticeOutbox:
    def __init__(self, monitor):
        self.monitor = monitor
        self.service = monitor.service
        self.task = None

    # ---- immutable notices and duplicate-safe receiver ----------------------
    def read(self):
        return TypeAdapter(list[Notice]).validate_python(self.monitor.read("a2a-notices.json", []))

    def save(self, rows):
        self.monitor.write("a2a-notices.json", [r.model_dump() for r in rows])

    def enqueue(self, topic, artifact, message, recipients):
        with self.monitor.data_lock:
            rows = self.read()
            known = {r.id for r in rows}
            changed = False
            for recipient in recipients:
                key = hashlib.sha256(
                    json.dumps([topic, artifact, message, recipient], ensure_ascii=False).encode()
                ).hexdigest()
                if key not in known:
                    rows.append(
                        Notice(
                            id=key,
                            recipient=recipient,
                            topic=topic,
                            artifact=artifact,
                            message=message,
                        )
                    )
                    self.service.store.event(
                        "judger",
                        "a2a.notice.queued",
                        recipient=recipient,
                        delivery_id=key,
                        topic=topic,
                        artifact=artifact,
                    )
                    known.add(key)
                    changed = True
            if changed:
                self.save(rows)

    def receive(self, command):
        with self.monitor.data_lock:
            row = next((r for r in self.read() if r.id == command.delivery_id), None)
            if row is None or (row.recipient, row.message, row.artifact) != (
                command.recipient,
                command.message,
                command.artifact,
            ):
                raise ValueError("system A2A message does not match the durable notice")
            self.service.team_folder(row.recipient)
            return self.service.store.message(
                "judger",
                row.recipient,
                row.message,
                row.artifact,
                delivery_id=row.id,
                transport="a2a",
                topic=row.topic,
            )

    # ---- network retries preserve delivery identity across lost acknowledgments
    async def flush(self):
        root = self.service.root
        for notice in self.read():
            if notice.state != "pending" or notice.next_at > time.time():
                continue
            error = ""
            try:
                async with asyncio.timeout(15):
                    result = json.loads(await self.service.send_notice(notice))
                if result.get("id") != notice.id or result.get("transport") != "a2a":
                    raise ValueError("A2A acknowledgement does not match the notice")
            except Exception as exc:
                error = self.service.redact(str(exc))[:1000] or type(exc).__name__
            if root != self.service.root:
                return
            with self.monitor.data_lock:
                rows = self.read()
                row = next(r for r in rows if r.id == notice.id)
                row.attempts += 1
                row.error = error
                row.next_at = time.time() + min(60, 2 ** min(row.attempts, 6)) if error else 0
                row.state = "pending" if error else "delivered"
                self.save(rows)
            self.service.store.event(
                "judger",
                "a2a.notice.retry" if error else "a2a.notice.delivered",
                delivery_id=notice.id,
                recipient=notice.recipient,
                topic=notice.topic,
                artifact=notice.artifact,
                error=error,
            )

    async def loop(self):
        while True:
            try:
                await self.flush()
            except Exception as exc:
                self.service.store.event(
                    "judger", "a2a.notice.error", message=self.service.redact(str(exc))[:1000]
                )
            await asyncio.sleep(2)

    async def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.loop())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

"""Real loopback A2A transport with synthetic notices; no model or official-site calls."""

import asyncio
import json
import socket

import pytest
import uvicorn
from test_judge_automation import lab as lab

from aworker.lab.api import create_lab_app
from aworker.lab.bridge import deliver_message


# ---- real local server, explicitly excluding startup model/background work ---
def test_system_notice_uses_a2a_and_lost_ack_does_not_duplicate_inbox(lab, monkeypatch):
    async def scenario():
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        lab.settings.lab_port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_lab_app(lab), log_level="error", access_log=False, lifespan="off")
        )
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.01)
            assert server.started
            outbox = lab.judger.notices
            outbox.enqueue(
                "judge-feedback", "fixture-candidate", "explicit fixture feedback", ["gpt-001"]
            )
            assert not lab.store.messages("gpt-001")
            original = lab.send_notice

            async def lost_ack(notice):
                await original(notice)
                raise TimeoutError("explicit lost acknowledgement fixture")

            monkeypatch.setattr(lab, "send_notice", lost_ack)
            await outbox.flush()
            assert outbox.read()[0].state == "pending"
            assert len(lab.store.messages("gpt-001")) == 1
            rows = outbox.read()
            rows[0].next_at = 0
            outbox.save(rows)
            monkeypatch.setattr(lab, "send_notice", original)
            await outbox.flush()
            assert outbox.read()[0].state == "delivered"
            assert outbox.read()[0].attempts == 2
            assert len(lab.store.messages("gpt-001")) == 1
            event = next(e for e in lab.store.events() if e["kind"] == "team.message")
            assert event["team"] == "judger" and event["data"]["transport"] == "a2a"
        finally:
            server.should_exit = True
            await task
            sock.close()

    asyncio.run(scenario())


# ---- system claims must exactly match the durable server-generated outbox ---
def test_forged_judger_or_modified_notice_is_rejected(lab):
    outbox = lab.judger.notices
    outbox.enqueue("sota", "fixture", "explicit fixture, not a real SOTA", ["gpt-001"])
    notice = outbox.read()[0]
    command = {
        "action": "message",
        "team": "judger",
        "recipient": notice.recipient,
        "message": notice.message + " forged",
        "artifact": notice.artifact,
        "delivery_id": notice.id,
    }
    with pytest.raises(ValueError, match="durable notice"):
        deliver_message(lab, json.dumps(command))
    command["message"] = notice.message
    command["delivery_id"] = "a" * 64
    with pytest.raises(ValueError, match="durable notice"):
        deliver_message(lab, json.dumps(command))
    assert not lab.store.messages("gpt-001")

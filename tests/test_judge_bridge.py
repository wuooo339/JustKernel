"""No real browser/login/network: verify owned bridge transport never replays a POST."""

import asyncio
import json
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

from aworker.lab.judge_bridge import BrowserBridge


# ---- BrowserFixture ---------------------------------------------------------
class BrowserFixture:
    principal = "fixture-account-hash-not-a-credential"

    def __init__(self):
        self.calls = 0

    # ---- explicit local fake, never an official submission -------------------
    async def _submit(self, *args):
        self.calls += 1
        return "fixture-only-not-an-official-id"

    def status(self):
        return {"opened": True, "connected": True, "state": "connected", "nickname": "fixture"}


# ---- fixture_request --------------------------------------------------------
def fixture_request(bridge, **update):
    key = uuid4().hex
    data = {
        "id": key,
        "worker_id": bridge.worker_id,
        "at": time.time(),
        "method": "submit",
        "args": [],
    }
    data.update(update)
    folder = bridge.spool / "requests"
    folder.mkdir(parents=True)
    path = folder / (key + ".request.json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, key


# ---- one operation, durable no-replay receipt -------------------------------
def test_browser_bridge_handles_each_request_once(tmp_path):
    bridge = BrowserBridge(tmp_path / "private", tmp_path / "spool")
    bridge.browser = BrowserFixture()
    path, key = fixture_request(bridge)
    asyncio.run(bridge.process(path))
    asyncio.run(bridge.process(path))
    assert bridge.browser.calls == 1
    reply = json.loads((path.parent / (key + ".reply.json")).read_text())
    assert reply["result"] == "fixture-only-not-an-official-id"


# ---- interrupted POST must remain uncertain, never silently retried ----------
def test_interrupted_browser_submission_is_not_replayed_after_restart(tmp_path):
    bridge = BrowserBridge(tmp_path / "private", tmp_path / "spool")
    bridge.browser = BrowserFixture()
    path, key = fixture_request(bridge, worker_id="old-worker")
    (path.parent / (key + ".started.json")).write_text("{}")
    asyncio.run(bridge.process(path))
    assert bridge.browser.calls == 0
    reply = json.loads((path.parent / (key + ".reply.json")).read_text())
    assert reply["error"]["kind"] == "SubmissionUncertain"


# ---- expired requests do not become a late official POST --------------------
def test_expired_browser_request_is_rejected_before_any_submission(tmp_path):
    bridge = BrowserBridge(tmp_path / "private", tmp_path / "spool")
    bridge.browser = BrowserFixture()
    path, key = fixture_request(bridge, at=time.time() - 180)
    asyncio.run(bridge.process(path))
    assert bridge.browser.calls == 0
    assert (
        json.loads((path.parent / (key + ".reply.json")).read_text())["error"]["kind"]
        == "ValueError"
    )


# ---- a duplicate invocation never touches the live browser or its heartbeat --
def test_duplicate_worker_exits_cleanly_and_preserves_the_existing_session(
    tmp_path, monkeypatch, capsys
):
    bridge = BrowserBridge(tmp_path / "private", tmp_path / "spool")
    bridge.browser = BrowserFixture()
    bridge.spool.mkdir()
    heartbeat = bridge.spool / "heartbeat.json"
    original = b'{"fixture":"existing-session-must-remain-untouched"}'
    heartbeat.write_bytes(original)

    def held_lock(*args):
        raise BlockingIOError("explicit already-running lock fixture")

    monkeypatch.setitem(
        sys.modules, "fcntl", SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=held_lock)
    )
    asyncio.run(bridge.serve("https://cannjudge.cn/"))
    assert bridge.browser.calls == 0
    assert heartbeat.read_bytes() == original
    assert "已在运行" in capsys.readouterr().out

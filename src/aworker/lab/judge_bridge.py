"""Project-owned browser worker on a local Linux desktop/WSLg, without cookie export."""

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from aworker.config import Settings
from aworker.lab.judge_browser import JudgeBrowser, JudgeRejected, SubmissionUncertain


# ---- BridgeRequest ----------------------------------------------------------
class BridgeRequest(BaseModel):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    worker_id: str
    at: float
    method: Literal["open", "check", "template", "submit", "receipt", "disconnect"]
    args: list


# ---- write_json -------------------------------------------------------------
def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


# ---- BrowserBridge ----------------------------------------------------------
class BrowserBridge:
    def __init__(self, root: Path, spool: Path):
        self.root, self.spool = root.resolve(), spool.resolve()
        self.worker_id = uuid4().hex
        self.browser = JudgeBrowser(Settings(_env_file=None, lab_private_root=root / "private"))
        self.busy = False

    # ---- fresh session status; credentials remain in this process -----------
    async def pulse(self):
        while True:
            write_json(
                self.spool / "heartbeat.json",
                {
                    "schema": "justkernel.judge.bridge.v1",
                    "at": time.time(),
                    "worker_id": self.worker_id,
                    "state": "ready",
                    "busy": self.busy,
                    "session": self.browser.status(),
                },
            )
            if not self.busy and self.browser.page:
                await self.browser._check()
            await asyncio.sleep(3)

    # ---- fixed official-site operations, one post at a time -----------------
    async def process(self, path):
        request = BridgeRequest.model_validate_json(path.read_bytes())
        output = path.parent / (request.id + ".reply.json")
        marker = path.parent / (request.id + ".started.json")
        if output.is_file():
            return
        response = {"id": request.id}
        self.busy = True
        try:
            if marker.exists():
                if request.method == "submit":
                    raise SubmissionUncertain(
                        "interrupted submission; automatic replay is forbidden"
                    )
                raise ValueError("interrupted browser operation; automatic replay is forbidden")
            if request.worker_id != self.worker_id or not -5 <= time.time() - request.at < 120:
                raise ValueError("browser bridge changed or request expired; no operation sent")
            write_json(marker, {"id": request.id, "method": request.method, "at": time.time()})
            response["result"] = await getattr(self.browser, "_" + request.method)(*request.args)
        except Exception as error:
            response["error"] = {
                "kind": type(error).__name__,
                "message": str(error)[:1500],
                "retry_after": error.retry_after if isinstance(error, JudgeRejected) else 0,
            }
        finally:
            response["session"] = self.browser.status()
            response["principal"] = self.browser.principal
            write_json(output, response)
            self.busy = False

    async def serve(self, initial_url=None):
        import fcntl

        self.root.mkdir(parents=True, exist_ok=True)
        self.spool.mkdir(parents=True, exist_ok=True)
        with (self.spool / "worker.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("官测浏览器服务已在运行，请使用现有窗口或从面板连接。", flush=True)
                return
            pulse = asyncio.create_task(self.pulse())
            try:
                if initial_url:
                    self.busy = True
                    try:
                        await self.browser._open(initial_url)
                    finally:
                        self.busy = False
                while True:
                    for path in sorted((self.spool / "requests").glob("*.request.json")):
                        await self.process(path)
                    await asyncio.sleep(0.25)
            finally:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)
                await self.browser._disconnect()
                write_json(
                    self.spool / "heartbeat.json",
                    {
                        "schema": "justkernel.judge.bridge.v1",
                        "at": time.time(),
                        "worker_id": self.worker_id,
                        "state": "stopped",
                        "busy": False,
                        "session": self.browser.status(),
                    },
                )


# ---- main ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--open")
    args = parser.parse_args()
    asyncio.run(BrowserBridge(args.root, args.spool).serve(args.open))


if __name__ == "__main__":
    main()

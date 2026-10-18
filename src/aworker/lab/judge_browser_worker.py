"""JSON-line transport for the project-owned ephemeral official-site browser."""

import asyncio
import json
import sys

from aworker.config import Settings
from aworker.lab.judge_browser import JudgeBrowser, JudgeRejected


# ---- serve ------------------------------------------------------------------
async def serve():
    # The parent passes only OS/browser environment, never model credentials.
    browser = JudgeBrowser(Settings(_env_file=None))
    allowed = {"open", "check", "template", "submit", "receipt", "disconnect"}
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = json.loads(line)
            reply = {"id": request.get("id")}
            try:
                method = request.get("method")
                if method not in allowed:
                    raise ValueError("unsupported official-site operation")
                if method == "open":
                    browser.settings.lab_judge_browser_channel = request.get("channel")
                    browser.settings.lab_judge_browser_disable_gpu = bool(
                        request.get("disable_gpu")
                    )
                reply["result"] = await getattr(browser, "_" + method)(*request.get("args", []))
            except Exception as exc:
                reply["error"] = {
                    "kind": type(exc).__name__,
                    "message": str(exc)[:1500],
                    "retry_after": exc.retry_after if isinstance(exc, JudgeRejected) else 0,
                }
            reply["session"] = browser.status()
            reply["principal"] = browser.principal
            print(json.dumps(reply, ensure_ascii=False), flush=True)
    finally:
        await browser._disconnect()


if __name__ == "__main__":
    # Standalone Python selects the Windows Proactor loop required by Playwright.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    asyncio.run(serve())

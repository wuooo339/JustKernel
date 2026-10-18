"""Project-owned ephemeral login session; no access to other browser profiles."""

import asyncio
import hashlib
import json
import logging
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel

ORIGIN = "https://cannjudge.cn"


# ---- typed browser status and ordinary transport failures -------------------
class JudgeSession(BaseModel):
    opened: bool = False
    connected: bool = False
    state: str = "closed"
    nickname: str = ""
    message: str = "点击连接，在项目登录窗口登录 CANN Judge。"


# ---- LoginRequired ----------------------------------------------------------
class LoginRequired(ValueError):
    pass


# ---- SubmissionUncertain ----------------------------------------------------
class SubmissionUncertain(ValueError):
    pass


# ---- TemplateChanged --------------------------------------------------------
class TemplateChanged(ValueError):
    pass


# ---- JudgeRejected ----------------------------------------------------------
class JudgeRejected(ValueError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


# ---- unwrap -----------------------------------------------------------------
def unwrap(body):
    if isinstance(body, dict) and body.get("code") == 0:
        return body.get("data", {})
    return body


# ---- JudgeBrowser -----------------------------------------------------------
class JudgeBrowser:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.temporary = None
        self.stderr = None
        self.responses = queue.Queue()
        self.process_lock = threading.Lock()
        self.driver = self.browser = self.context = self.page = None
        self.state = JudgeSession()
        self.principal = None

    # ---- owned child process with private temporary storage -----------------
    def _start(self):
        if self.process and self.process.poll() is None:
            return
        self._stop_process()
        root = self.settings.lab_private_root.resolve()
        folder = root / "browser-temporary"
        folder.mkdir(parents=True, exist_ok=True)
        if not folder.resolve().is_relative_to(root):
            raise ValueError("invalid browser temporary directory")
        self.temporary = tempfile.TemporaryDirectory(prefix="judge-", dir=folder)
        self.responses = queue.Queue()
        try:
            self.stderr = (Path(self.temporary.name) / "worker.log").open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                [
                    sys._base_executable if sys.platform == "win32" else sys.executable,
                    "-I",
                    "-u",
                    "-m",
                    "aworker.lab.judge_browser_worker",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                text=True,
                encoding="utf-8",
                env=self.settings.judge_browser_environment(Path(self.temporary.name)),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception:
            self._stop_process()
            raise

        def read_responses(pipe, responses):
            try:
                for line in pipe:
                    responses.put(line)
            except (OSError, UnicodeError):
                pass
            finally:
                responses.put(None)

        threading.Thread(
            target=read_responses,
            args=(self.process.stdout, self.responses),
            name="justkernel-judge-responses",
            daemon=True,
        ).start()

    def _send(self, method, args):
        if method not in {"open", "check", "template", "submit", "receipt", "disconnect"}:
            raise ValueError("unsupported official-site operation")
        if self.settings.lab_judge_bridge:
            return self._bridge_call(method, args)
        with self.process_lock:
            self._start()
            nonce = uuid4().hex
            request = {"id": nonce, "method": method, "args": args}
            if method == "open":
                request["channel"] = self.settings.lab_judge_browser_channel
                request["disable_gpu"] = self.settings.lab_judge_browser_disable_gpu
            try:
                self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
                line = self.responses.get(timeout=150)
                if line is None:
                    raise ValueError("official-site browser worker disconnected")
                reply = json.loads(line)
                if reply.get("id") != nonce:
                    raise ValueError("official-site browser response mismatch")
            except Exception:
                self._stop_process()
                if method == "submit":
                    raise SubmissionUncertain(
                        "官测连接中断，提交状态不确定；禁止自动重发。"
                    ) from None
                raise ValueError("官测窗口连接中断，请从面板重新连接。") from None
            return self._accept_reply(reply)

    # ---- optional local Linux browser runtime, same credential boundaries ---
    def _bridge_call(self, method, args):
        with self.process_lock:
            folder = self.settings.lab_judge_bridge.resolve()
            heartbeat = folder / "heartbeat.json"
            worker = (
                json.loads(heartbeat.read_text(encoding="utf-8")) if heartbeat.is_file() else {}
            )
            if (
                worker.get("schema") != "justkernel.judge.bridge.v1"
                or worker.get("state") != "ready"
                or not -5 <= time.time() - worker.get("at", 0) < 30
            ):
                raise ValueError("项目的本机浏览器 Worker 不在线；尚未发送官测。")
            nonce = uuid4().hex
            requests = folder / "requests"
            requests.mkdir(exist_ok=True)
            path = requests / (nonce + ".request.json")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "id": nonce,
                        "worker_id": worker["worker_id"],
                        "method": method,
                        "args": args,
                        "at": time.time(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
            response = requests / (nonce + ".reply.json")
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                if response.is_file():
                    reply = json.loads(response.read_text(encoding="utf-8"))
                    if reply.get("id") != nonce:
                        raise ValueError("browser bridge response identity mismatch")
                    return self._accept_reply(reply)
                time.sleep(0.2)
            if method == "submit":
                raise SubmissionUncertain("官测浏览器响应超时，提交状态不确定，禁止自动重发。")
            raise ValueError("项目浏览器响应超时，请检查其窗口和运行日志。")

    def _accept_reply(self, reply):
        self.state = JudgeSession.model_validate(reply["session"])
        self.principal = reply.get("principal")
        if reply.get("error"):
            kinds = {
                "LoginRequired": LoginRequired,
                "SubmissionUncertain": SubmissionUncertain,
                "JudgeRejected": JudgeRejected,
                "TemplateChanged": TemplateChanged,
            }
            error = reply["error"]
            cls = kinds.get(error["kind"], ValueError)
            if cls is JudgeRejected:
                raise cls(error["message"], error.get("retry_after", 0))
            raise cls(error["message"])
        return reply["result"]

    async def call(self, method, *args):
        return await asyncio.shield(asyncio.to_thread(self._send, method, args))

    def status(self):
        if self.settings.lab_judge_bridge:
            heartbeat = self.settings.lab_judge_bridge / "heartbeat.json"
            worker = (
                json.loads(heartbeat.read_text(encoding="utf-8")) if heartbeat.is_file() else {}
            )
            if (
                worker.get("state") == "ready"
                and worker.get("schema") == "justkernel.judge.bridge.v1"
                and -5 <= time.time() - worker.get("at", 0) < 30
            ):
                self.state = JudgeSession.model_validate(worker["session"])
            else:
                self.state = JudgeSession(
                    state="closed", message="等待本机独立官测窗口启动并登录。"
                )
        return self.state.model_dump()

    # ---- user-controlled sign-in; no password or cookie export ---------------
    async def _open(self, url):
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc != "cannjudge.cn":
            raise ValueError("only the official HTTPS CANN Judge login is supported")
        if self.browser and self.browser.is_connected() and self.page and not self.page.is_closed():
            await self.page.bring_to_front()
            return await self._check()
        from playwright.async_api import async_playwright

        try:
            self.driver = await asyncio.wait_for(async_playwright().start(), 30)
            options = {"headless": False, "chromium_sandbox": True, "timeout": 45000}
            if self.settings.lab_judge_browser_disable_gpu:
                options["args"] = ["--disable-gpu"]
            try:
                self.browser = await self.driver.chromium.launch(
                    channel=self.settings.lab_judge_browser_channel, **options
                )
            except Exception as exc:
                denied = any(
                    word in str(exc).lower()
                    for word in ("policy", "permission", "eperm", "access denied")
                )
                if (
                    denied
                    or not self.settings.lab_judge_browser_channel
                    or not Path(self.driver.chromium.executable_path).is_file()
                ):
                    raise
                # Installed browser versions can be incompatible with the SDK.
                # Use its matching runtime, with the same sandbox and fresh context.
                self.browser = await self.driver.chromium.launch(**options)
            self.context = await self.browser.new_context(accept_downloads=False)
            self.page = await self.context.new_page()
            await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            self.state = JudgeSession(
                opened=True,
                state="awaiting-login",
                message="请在项目打开的官方窗口登录，面板会自动检测。",
            )
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Judge browser startup: %s: %s", type(exc).__name__, str(exc)[-6000:]
            )
            await self._disconnect()
            self.state = JudgeSession(
                state="startup-error",
                message=(
                    "官测登录窗口未能启动，尚未提交代码。"
                    "模型搜索继续运行；请检查本机浏览器运行时。"
                    "可运行 python -m playwright install chromium 安装配套浏览器。"
                ),
            )
            raise ValueError(self.state.message) from None
        return await self._check()

    async def _identity(self):
        if not self.context or not self.page or self.page.is_closed():
            raise LoginRequired("请从面板打开官测登录窗口。")
        if urlsplit(self.page.url).netloc != "cannjudge.cn":
            raise LoginRequired("请完成官方登录并返回 CANN Judge 页面。")
        # Read only the identity selected by login in THIS newly created context.
        # No storage_state(), cookies(), profile copying or access to the app browser.
        claimed = await self.page.evaluate("""() => {
          try { const u=JSON.parse(localStorage.getItem('cannjudge_user')||'null');
            return u ? {ID:u.ID,_id:u._id} : null; } catch { return null; }
        }""")
        if not claimed or not re.fullmatch(r"[0-9a-f]{24}", str(claimed.get("_id", ""))):
            raise LoginRequired("请在项目打开的官方窗口登录。")
        number = str(claimed.get("ID", ""))
        if not number.isdigit():
            raise LoginRequired("官方登录尚未完成。")
        response = await self.context.request.get(
            ORIGIN + "/api/users/me/" + number,
            timeout=20000,
            max_retries=0,
            max_redirects=0,
        )
        if response.status != 200:
            raise LoginRequired("官方登录已失效，请在登录窗口重新登录。")
        user = unwrap(await response.json())
        if isinstance(user.get("user"), dict):
            user = user["user"]
        if user.get("_id") != claimed["_id"] or str(user.get("ID")) != number:
            raise LoginRequired("官方身份校验未通过，请重新登录。")
        self.state = JudgeSession(
            opened=True,
            connected=True,
            state="connected",
            nickname=str(user.get("nickname", ""))[:80],
            message="已连接官测登录会话，凭据不会进入模型上下文。",
        )
        self.principal = hashlib.sha256(user["_id"].encode()).hexdigest()
        return user["_id"]

    async def _check(self):
        try:
            await self._identity()
        except LoginRequired as exc:
            self.state = JudgeSession(
                opened=bool(self.page and not self.page.is_closed()),
                state="awaiting-login",
                message=str(exc),
            )
        except Exception:
            self.state = JudgeSession(
                opened=bool(self.page and not self.page.is_closed()),
                state="connection-error",
                message="暂时无法校验官方登录会话。",
            )
        return self.status()

    # ---- exact official API operations using this context's session ---------
    async def _template(self, problem_id):
        await self._identity()
        if not re.fullmatch(r"[0-9a-f]{24}", problem_id):
            raise ValueError("invalid official problem identity")
        response = await self.context.request.get(
            ORIGIN + "/api/problems/" + problem_id + "/template",
            timeout=30000,
            max_retries=0,
            max_redirects=0,
        )
        if response.status != 200:
            raise ValueError("无法核验官方工程模板，暂不提交。")
        return unwrap(await response.json())

    async def _submit(self, problem_id, files, expected_principal=None):
        user_id = await self._identity()
        if expected_principal and self.principal != expected_principal:
            raise LoginRequired("登录账户已改变，请在面板确认后重新开启自动官测。")
        if not re.fullmatch(r"[0-9a-f]{24}", problem_id):
            raise ValueError("invalid official problem identity")
        try:
            response = await self.context.request.post(
                ORIGIN + "/api/submissions/submit",
                data={"problemId": problem_id, "userId": user_id, "files": files},
                timeout=90000,
                max_retries=0,
                max_redirects=0,
            )
        except Exception:
            raise SubmissionUncertain("提交响应中断，官方可能已收件；禁止自动重发。") from None
        if response.status in {401, 403}:
            self.state.connected = False
            raise LoginRequired("官方要求重新登录或确认参赛权限。")
        if response.status == 429:
            retry = response.headers.get("retry-after", "60")
            raise JudgeRejected(
                "官方限制提交频率，按 Retry-After 等待。", int(retry) if retry.isdigit() else 60
            )
        if response.status >= 500:
            raise SubmissionUncertain("官方服务异常，提交状态不确定；禁止自动重发。")
        try:
            body = await response.json()
        except Exception:
            raise SubmissionUncertain("官方未返回可识别回执；禁止自动重发。") from None
        if not response.ok or ("code" in body and body["code"] != 0):
            raise JudgeRejected(str(body.get("msg") or body.get("message") or "官方拒绝提交")[:500])
        value = str(unwrap(body).get("submissionId", ""))
        if not re.fullmatch(r"(?:[0-9a-f]{24}|[0-9]{1,12})", value):
            raise SubmissionUncertain("官方响应中没有提交 ID，禁止自动重发。")
        return value

    async def _receipt(self, submission_id):
        user_id = await self._identity()
        if not re.fullmatch(r"(?:[0-9a-f]{24}|[0-9]{1,12})", submission_id):
            raise ValueError("invalid official submission identity")
        response = await self.context.request.get(
            ORIGIN + "/api/submissions/" + submission_id,
            params={"userId": user_id},
            timeout=30000,
            max_retries=0,
            max_redirects=0,
        )
        if response.status in {401, 403}:
            raise LoginRequired("读取本人回执需要重新登录。")
        if response.status != 200:
            raise ValueError("官方回执暂不可读，请等待下一次同步。")
        return unwrap(await response.json())

    # ---- close only the project-owned window and ephemeral context ----------
    async def _disconnect(self):
        import contextlib

        for item in (self.context, self.browser, self.driver):
            if item:
                with contextlib.suppress(Exception):
                    if item is self.driver:
                        await item.stop()
                    else:
                        await item.close()
        self.driver = self.browser = self.context = self.page = None
        self.state = JudgeSession()
        self.principal = None
        return self.status()

    def _stop_process(self):
        import contextlib

        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    with contextlib.suppress(OSError):
                        pipe.close()
            self.process = None
        if self.stderr:
            self.stderr.close()
            self.stderr = None
        if self.temporary:
            target = Path(self.temporary.name).resolve()
            if not target.is_relative_to(self.settings.lab_private_root.resolve()):
                raise ValueError("refusing cleanup outside browser private root")
            try:
                self.temporary.cleanup()
            except OSError:
                logging.getLogger(__name__).warning(
                    "Browser temporary cleanup is pending; remove after closing its window: %s",
                    target,
                )
            self.temporary = None
        self.state = JudgeSession()
        self.principal = None

    async def close(self):
        if not self.process:
            return
        try:
            await self.call("disconnect")
        finally:
            await asyncio.to_thread(self._locked_stop)

    def _locked_stop(self):
        with self.process_lock:
            self._stop_process()

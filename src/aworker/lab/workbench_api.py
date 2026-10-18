"""Local-only workbench: connection profiles, operator intake, assistants and SSH PTY."""

import asyncio
import contextlib
import json
import platform
import re
from pathlib import Path

import asyncssh
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from aworker.lab.model_settings import APIModelSave, save_api_model
from aworker.lab.operators import OperatorDraft
from aworker.lab.servers import ServerSave, parse_ssh_text, probe_server
from aworker.lab.setup_agent import SetupJobs, SetupRequest


# ---- ConnectionText ---------------------------------------------------------
class ConnectionText(BaseModel):
    text: str = Field(min_length=1, max_length=16000)


# ---- HostTrust --------------------------------------------------------------
class HostTrust(BaseModel):
    public_key: str = Field(max_length=4000)
    fingerprint: str = Field(max_length=200)


# ---- WatchJudge -------------------------------------------------------------
class WatchJudge(BaseModel):
    enabled: bool


# ---- StageJudge -------------------------------------------------------------
class StageJudge(BaseModel):
    team: str = Field(min_length=1, max_length=64)


# ---- TrackJudge -------------------------------------------------------------
class TrackJudge(BaseModel):
    candidate_id: str
    submission_id: str


# ---- AutomateJudge ----------------------------------------------------------
class AutomateJudge(BaseModel):
    enabled: bool = True
    max_submissions: int = Field(default=50, ge=1, le=100000)
    selector_model: str | None = None


# ---- workbench_router -------------------------------------------------------
def workbench_router(service) -> APIRouter:
    router = APIRouter(prefix="/workspace")
    service.setup_jobs = SetupJobs(service)

    @router.get("/status")
    async def status():
        return {
            "version": "workbench-v1",
            "operator": service.operator,
            "execution_mode": service.execution_mode,
            "operators": service.catalog.catalog(),
            "servers": service.servers.catalog(),
            "credential_directory": str(service.servers.folder),
            "client_platform": platform.system(),
            "aliases": service.servers.aliases(),
        }

    @router.get("/defaults")
    async def defaults():
        return {
            "constraints": (Path(__file__).parent / "resources/default_constraints.md").read_text(
                encoding="utf-8"
            )
        }

    @router.get("/judge")
    async def judge_status():
        return service.judger.status()

    @router.get("/simulator")
    async def simulator_status():
        return {**service.simulator.status(), "jobs": service.simulator.jobs()}

    @router.get("/simulator/jobs/{key}")
    async def simulation_log(key: str):
        return service.simulator.logs(key)

    @router.post("/judge/sync")
    async def sync_judge():
        return await service.judger.sync()

    @router.post("/judge/watch")
    async def watch_judge(request: WatchJudge):
        return await service.judger.watch(request.enabled)

    @router.post("/judge/stage")
    async def stage_judge(request: StageJudge):
        return service.judger.stage(request.team)

    @router.get("/judge/packages/{key}")
    async def judge_package(key: str):
        return FileResponse(
            service.judger.package(key), filename="ConfusionMulGrad_" + key + ".zip"
        )

    @router.post("/judge/track")
    async def track_judge(request: TrackJudge):
        return service.judger.track(request.candidate_id, request.submission_id)

    @router.post("/judge/session/open")
    async def open_judge(request: AutomateJudge):
        manifest = json.loads(
            (service.root / "challenge/manifest.json").read_text(encoding="utf-8")
        )
        source = manifest.get("input_source", {})
        if not source.get("problem_url"):
            raise ValueError("当前算子没有官方题目链接。")
        session = await service.judger.browser.call(
            "open", source["problem_url"].rstrip("/") + "/submit"
        )
        await service.judger.automation.configure(
            request.enabled, request.max_submissions, selector_model=request.selector_model
        )
        return {"session": session, "automation": service.judger.automation.status()}

    @router.post("/judge/session/check")
    async def check_judge():
        return await service.judger.browser.call("check")

    @router.post("/judge/session/close")
    async def close_judge():
        if service.judger.automation.busy:
            raise ValueError("请先等待正在提交的官方响应，避免产生不确定状态。")
        await service.judger.automation.configure(
            False,
            service.judger.automation.configuration()["max_submissions"],
            selector_model=service.judger.automation.configuration().get("selector_model"),
        )
        return await service.judger.browser.call("disconnect")

    @router.post("/judge/automation")
    async def automate_judge(request: AutomateJudge):
        return await service.judger.automation.configure(
            request.enabled, request.max_submissions, selector_model=request.selector_model
        )

    @router.post("/judge/candidates/{key}/submit")
    async def submit_judge(key: str):
        return await service.judger.automation.submit(key, automatic=True)

    @router.get("/judge/candidates/{key}")
    async def judge_code(key: str):
        return service.judger.code(key)

    @router.post("/judge/candidates/{key}/feedback")
    async def judge_feedback(key: str):
        return service.judger.feedback(key)

    @router.post("/operators/{key}/keep-only")
    async def keep_operator(key: str):
        return service.reset_operators(key)

    @router.post("/models")
    async def save_model(request: APIModelSave):
        return save_api_model(service, request)

    @router.post("/models/{key}/test")
    async def test_model(key: str):
        try:
            model = service.registry.build(key)
            reply = await asyncio.wait_for(
                model.ainvoke([HumanMessage(content="Reply only OK.")]), 90
            )
            return {"id": key, "connected": True, "answer": str(reply.content)[:300]}
        except Exception as exc:
            return {"id": key, "connected": False, "error": service.redact(str(exc))[:2000]}

    @router.post("/operators", status_code=201)
    async def create_operator(request: OperatorDraft):
        return service.catalog.create(request)

    @router.post("/operators/{key}/activate")
    async def activate_operator(key: str):
        return service.select_operator(key)

    @router.post("/servers/parse")
    async def parse_connection(request: ConnectionText):
        return parse_ssh_text(request.text)

    @router.post("/servers")
    async def save_server(request: ServerSave):
        active = service.servers.data()["active"] == request.profile.id
        if active:
            service.require_idle()
        result = service.servers.save(request)
        if active:
            service._bind_runner()
        return result

    @router.post("/servers/{key}/activate")
    async def activate_server(key: str):
        return service.select_server(key)

    @router.post("/servers/{key}/probe")
    async def probe(key: str):
        return await asyncio.to_thread(probe_server, service.servers, key)

    @router.post("/servers/{key}/host-key")
    async def host_key(key: str):
        return await service.servers.host_key(key)

    @router.post("/servers/{key}/trust")
    async def trust_host(key: str, request: HostTrust):
        public_key = asyncssh.import_public_key(request.public_key)
        if public_key.get_fingerprint() != request.fingerprint:
            raise ValueError("host fingerprint does not match the provided public key")
        profile = service.servers.get(key).model_copy(update={"trusted_key": request.public_key})
        service.servers.save(ServerSave(profile=profile))
        return {"trusted": request.fingerprint}

    @router.post("/setup", status_code=202)
    async def setup(request: SetupRequest):
        return {"id": service.setup_jobs.start(request), "state": "running"}

    @router.get("/setup/{key}")
    async def setup_status(key: str):
        return service.setup_jobs.get(key)

    @router.get("/jobs/{key}/logs")
    async def job_logs(key: str):
        if not re.fullmatch(r"[a-f0-9]{32}", key):
            raise ValueError("invalid job identity")
        job = next((j for j in service.store.snapshot()["jobs"] if j["id"] == key), None)
        if job is None:
            raise ValueError("job does not belong to this operator workspace")
        folder = service.root / "jobs" / key
        logs = {}
        for name in ("remote.log", "transport.log", "result.json"):
            path = folder / name
            if path.is_file():
                logs[name] = service.redact(
                    path.read_text(encoding="utf-8", errors="replace")[-24000:]
                )
        return {"job": {k: v for k, v in job.items() if k != "token"}, "logs": logs}

    @router.websocket("/terminal/{key}")
    async def terminal(websocket: WebSocket, key: str):
        host = websocket.headers.get("host", "")
        origin = websocket.headers.get("origin")
        if (
            host.split(":")[0] not in {"127.0.0.1", "localhost", "testserver"}
            or origin
            and origin not in {"http://" + host, "https://" + host}
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            profile = service.servers.get(key)
            async with (
                asyncssh.connect(profile.host, **service.servers.async_options(key)) as conn,
                conn.create_process(
                    term_type="xterm-256color", term_size=(100, 28), stderr=asyncssh.STDOUT
                ) as process,
            ):
                await websocket.send_json({"type": "connected", "server": key})

                async def output():
                    while data := await process.stdout.read(4096):
                        await websocket.send_json({"type": "output", "data": data})

                async def input_stream():
                    while True:
                        raw = await websocket.receive_text()
                        if len(raw) > 66000:
                            raise ValueError("terminal message is too large")
                        message = json.loads(raw)
                        if message.get("type") == "input" and isinstance(message.get("data"), str):
                            process.stdin.write(message["data"])
                        elif message.get("type") == "resize":
                            process.change_terminal_size(
                                max(20, min(240, int(message["cols"]))),
                                max(5, min(80, int(message["rows"]))),
                            )
                        else:
                            raise ValueError("unsupported terminal message")

                tasks = [asyncio.create_task(output()), asyncio.create_task(input_stream())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            with contextlib.suppress(Exception):
                await websocket.send_json(
                    {"type": "error", "message": service.redact(str(exc))[:2000]}
                )
        finally:
            with contextlib.suppress(Exception):
                await websocket.close()

    return router

"""One local HTTP app: dashboard, typed control API, SSE and A2A."""

import asyncio
import json
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import asyncssh
import httpx
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.requests import HTTPConnection

from aworker.lab.bridge import TeamExecutor, TeamSwarm
from aworker.lab.continuous import SwarmPlan
from aworker.lab.dashboard import DashboardFiles
from aworker.lab.domain import Specialist
from aworker.lab.export import execution_record
from aworker.lab.service import LabService
from aworker.lab.workbench_api import workbench_router
from aworker.server.card import build_agent_card


# ---- requests ---------------------------------------------------------------
class DashboardCommand(BaseModel):
    team: str = Field(min_length=1, max_length=64)
    prompt: str = Field(default="", max_length=100_000)


# ---- JoinTeamRequest --------------------------------------------------------
class JoinTeamRequest(BaseModel):
    team: str = Field(min_length=1, max_length=64)
    runtime: Literal["deepagents"] = "deepagents"
    model: str = Field(min_length=1, max_length=200)
    members: list[Specialist] | None = None


# ---- AutoTeamsRequest -------------------------------------------------------
class AutoTeamsRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    model: str | None = Field(default=None, min_length=1, max_length=200)


# ---- SwarmRequest -----------------------------------------------------------
class SwarmRequest(BaseModel):
    teams: list[str] = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=100_000)


# ---- RosterRequest ----------------------------------------------------------
class RosterRequest(BaseModel):
    members: list[Specialist] = Field(min_length=1, max_length=16)


# ---- TeamMessage ------------------------------------------------------------
class TeamMessage(BaseModel):
    team: str
    recipient: str
    message: str = Field(min_length=1, max_length=8000)
    artifact: str | None = None


# ---- local_control ----------------------------------------------------------
def local_control(request: HTTPConnection):
    if request.scope["type"] == "websocket":
        # The terminal endpoint validates its WebSocket host and Origin before accepting.
        return
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        # Root app and mounted API share the same host/port; base_url may include mount path.
        from urllib.parse import urlsplit

        parsed, base = urlsplit(origin), urlsplit(str(request.url))
        if parsed.scheme != base.scheme or parsed.netloc != base.netloc:
            raise HTTPException(403, "same-origin local dashboard required")
    host = request.headers.get("host", "").split(":")[0]
    if host not in {"127.0.0.1", "localhost", "testserver"}:
        raise HTTPException(403, "local host required")


# ---- create_lab_app ---------------------------------------------------------
def create_lab_app(service: LabService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        await service.simulator.start()
        await service.judger.notices.start()
        if service.judger.read("watch.json", {}).get("enabled"):
            await service.judger.watch(True)
        await service.judger.automation.start()
        await service.swarm.start()
        yield
        await service.close()

    app = FastAPI(title="JustKernel", version="0.2.0", lifespan=lifespan)
    api = FastAPI(
        title="JustKernel control", version="0.2.0", dependencies=[Depends(local_control)]
    )

    @api.exception_handler(ValueError)
    @api.exception_handler(OSError)
    @api.exception_handler(asyncssh.Error)
    @api.exception_handler(subprocess.SubprocessError)
    @api.exception_handler(httpx.HTTPError)
    async def invalid(request, exc):
        return JSONResponse({"detail": service.redact(str(exc))}, status_code=409)

    @api.exception_handler(RequestValidationError)
    async def invalid_fields(request, exc):
        # Never echo password fields or image bodies from a rejected request.
        return JSONResponse(
            {
                "detail": [
                    {"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()
                ]
            },
            status_code=422,
        )

    api.include_router(workbench_router(service))

    @api.get("/health")
    async def health():
        return {
            "ok": True,
            "generation": "deepagents-v2",
            "tool_contract": "recoverable-evaluation-v1",
            "iteration_contract": "evidence-driven-v1",
            "workbench": "workbench-v1",
            "harness": "deepagents",
            "npu_configured": service.runner is not None,
        }

    @api.get("/snapshot")
    def snapshot():
        data = service.store.snapshot(history_limit=100)
        for job in data["jobs"]:
            job.pop("token", None)
        data["teams"] = [t for t in data["teams"] if t["runtime"] == "deepagents"]
        data["experiences"] = service.store.experiences()
        data["public"] = service.public(include_source=False)
        data["operator"] = service.operator
        data["setup_running"] = bool(service.setup_jobs.tasks)
        data["judge_submission_running"] = service.judger.automation.busy
        data["continuous"] = service.swarm.status()
        data["iterations"] = service.iterations.snapshot()
        data["judge_selector_running"] = service.judger.automation.selector.status()["running"]
        data["judge_budget"] = service.judger.automation.budget()
        data["simulation"] = service.simulator.status()
        data["simulation_jobs"] = service.simulator.jobs(summary=True)
        data["a2a_notices"] = [
            n.model_dump(exclude={"message"}) for n in service.judger.notices.read()
        ]
        return data

    @api.get("/events")
    async def events(after: int = 0):
        return service.store.events(after)

    @api.get("/events/bootstrap")
    def dashboard_events():
        return JSONResponse(service.store.dashboard_events(), headers={"Cache-Control": "no-store"})

    @api.get("/challenge")
    async def challenge():
        folder = service.root / "challenge"
        cases = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        source = manifest.get("input_source", {})
        return {
            "statement": (folder / "statement.md").read_text(encoding="utf-8"),
            "constraints": (folder / "CONSTRAINTS.md").read_text(encoding="utf-8"),
            "cases": cases,
            "manifest": manifest,
            "input_correspondence": {
                "local_count": len(cases),
                "official_count": source.get("official_case_count"),
                "confirmed_count": sum(bool(c.get("official_case_id")) for c in cases),
                "status": "provisional"
                if manifest.get("not_official_hidden_cases")
                else "unspecified",
            },
        }

    @api.get("/control/status")
    async def control_status():
        return {
            "harness": "deepagents",
            "npu_configured": service.runner is not None,
            "max_active_devices": service.settings.lab_max_active,
            "langsmith_enabled": service.settings.lab_langsmith_enabled,
            "models": service.registry.catalog(),
            "operator": service.operator,
            "execution_mode": service.execution_mode,
            "team_concurrency": service.settings.lab_team_concurrency,
        }

    @api.get("/control/models")
    async def models():
        return {"available": True, "harness": "deepagents", "models": service.registry.catalog()}

    @api.get("/control/teams/{team}/source")
    async def source(team: str):
        return service.candidate(team)

    @api.post("/control/teams")
    async def join(request: JoinTeamRequest):
        service.join(request.team, request.runtime, request.model)
        if request.members:
            service.set_members(request.team, request.members)
        return {"team": request.team, "runtime": "deepagents", "model": request.model}

    @api.post("/control/teams/{team}/members")
    async def members(team: str, request: RosterRequest):
        service.set_members(team, request.members)
        return {"team": team, "members": request.members}

    @api.post("/control/teams/{team}/model")
    async def rebind_model(team: str, request: JoinTeamRequest):
        if request.team != team:
            raise ValueError("team identity mismatch")
        service.rebind_model(team, request.model)
        return {"team": team, "model": request.model}

    @api.post("/control/teams/auto")
    async def auto_teams(request: AutoTeamsRequest):
        return {"teams": service.auto_teams(request.count, request.model)}

    @api.post("/control/swarm/start", status_code=202)
    async def start_swarm(request: SwarmRequest):
        return service.start_swarm(request.teams, request.prompt)

    @api.get("/control/swarm/continuous")
    async def continuous_status():
        return service.swarm.status()

    @api.post("/control/swarm/continuous", status_code=202)
    async def continuous_swarm(request: SwarmPlan):
        plan = SwarmPlan.model_validate(
            {**service.swarm.status(), **request.model_dump(exclude_unset=True)}
        )
        result = await service.swarm.configure(plan)
        if plan.enabled:
            config = service.judger.automation.configuration()
            await service.judger.automation.configure(
                True,
                config["max_submissions"],
                plan.model
                if plan.strategy == "baseline" and plan.model
                else config.get("selector_model"),
            )
        return result

    @api.post("/control/teams/{team}/leave")
    async def leave(team: str):
        service.leave(team)
        return {"team": team, "active": False}

    @api.post("/control/{action}", status_code=202)
    async def control(action: Literal["run", "evaluate"], request: DashboardCommand):
        key = service.start_operation(request.team, action, request.prompt)
        return {"operation_id": key, "state": "running", "team": request.team}

    @api.post("/control/operations/{key}/cancel")
    async def cancel(key: str):
        service.cancel_operation(key)
        return {"operation_id": key, "state": "cancelling"}

    @api.post("/control/messages")
    async def message(request: TeamMessage):
        service.team_folder(request.team)
        service.team_folder(request.recipient)
        return json.loads(
            await service.send_message(
                request.team, request.recipient, request.message, request.artifact
            )
        )

    @api.get("/experiences")
    async def experiences():
        return service.store.experiences()

    @api.get("/public")
    async def public():
        return service.public(include_source=False)

    @api.get("/public/{artifact}/source")
    async def public_source(artifact: str):
        return {"source": service.public_code(artifact)}

    @api.get("/stream")
    async def stream(request: Request, after: int = 0):
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "invalid event cursor") from None

        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                entries = service.store.events(cursor)
                for entry in entries:
                    cursor = entry["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(entry, ensure_ascii=False)}\n\n"
                if not entries:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @api.get("/export")
    async def export():
        return JSONResponse(
            execution_record(service),
            headers={"Content-Disposition": 'attachment; filename="justkernel-events.json"'},
        )

    app.mount("/api/lab", api)
    # Keep A2A separate from the dashboard root while sharing the same process and journal.
    swarm = TeamSwarm(service)
    settings = service.settings.model_copy(
        update={
            "require_llm_credential": False,
            "public_url": f"http://{service.settings.lab_host}:{service.settings.lab_port}/a2a",
        }
    )
    card = build_agent_card(settings, swarm)
    card.supported_interfaces[0].url += "/"
    del card.capabilities.extensions[:]

    async def current_card(original):
        fresh = build_agent_card(settings, TeamSwarm(service))
        fresh.supported_interfaces[0].url += "/"
        del fresh.capabilities.extensions[:]
        return fresh

    handler = DefaultRequestHandler(
        agent_executor=TeamExecutor(service), task_store=InMemoryTaskStore(), agent_card=card
    )
    a2a = FastAPI()
    add_a2a_routes_to_fastapi(
        a2a,
        agent_card_routes=create_agent_card_routes(card, current_card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    )
    app.mount("/a2a", a2a)

    @app.get("/.well-known/agent-card.json")
    async def agent_card():
        # Rebuild metadata when teams join/leave; the executor also reads the live registry.
        from google.protobuf.json_format import MessageToDict

        return JSONResponse(MessageToDict(await current_card(card)))

    web = Path(__file__).parent / "resources" / "web"
    app.mount("/", DashboardFiles(directory=web), name="dashboard")
    return app

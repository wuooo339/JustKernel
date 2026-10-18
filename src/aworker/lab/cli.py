"""Single entry point for the complete local JustKernel application."""

import argparse
import asyncio
import json
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn

from aworker.config import Settings
from aworker.lab.api import create_lab_app
from aworker.lab.bridge import wait_result
from aworker.lab.export import execution_record
from aworker.lab.inputs import import_input_cases
from aworker.lab.lifecycle import recover_model_work, service_lock
from aworker.lab.service import LabService


# ---- arguments --------------------------------------------------------------
def arguments():
    parser = argparse.ArgumentParser(
        prog="justkernel", description="Unified Deep Agents kernel lab"
    )
    parser.add_argument("--root", type=Path)
    sub = parser.add_subparsers(dest="action")
    demo = sub.add_parser("demo", help="lightweight preview; no template, API key, CANN or NPU")
    demo.add_argument("--host")
    demo.add_argument("--port", type=int)
    demo.add_argument("--open", action="store_true", dest="open_browser")
    serve = sub.add_parser("serve", help="serve dashboard, API and A2A in one process")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--supervise", action="store_true", help="recover native runtime crashes")
    serve.add_argument(
        "--open", action="store_true", dest="open_browser", help="open the local dashboard"
    )
    initialize = sub.add_parser("init", help="prepare the default official challenge and teams")
    initialize.add_argument("--team")
    initialize.add_argument("--model")
    join = sub.add_parser("join")
    join.add_argument("team")
    join.add_argument("--model", required=True)
    run = sub.add_parser("run")
    run.add_argument("team")
    run.add_argument("--prompt", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("team")
    leave = sub.add_parser("leave")
    leave.add_argument("team")
    sub.add_parser("doctor")
    sub.add_parser("snapshot")
    export = sub.add_parser("export")
    export.add_argument("--output", type=Path)
    inputs = sub.add_parser("import-inputs")
    inputs.add_argument("--inputs", type=Path, required=True)
    return parser.parse_args()


# ---- initialize -------------------------------------------------------------
def initialize(service: LabService, team: str | None = None, model: str | None = None):
    snapshot = service.store.snapshot()
    if any(o["state"] == "running" for o in snapshot["operations"]) or any(
        j["state"] in {"running", "queued"} for j in snapshot["jobs"]
    ):
        raise ValueError("finish existing work before initialization/migration")
    # Preserve old transcripts and device evidence without treating them as new harness runs.
    for old in snapshot["teams"]:
        if old["runtime"] != "deepagents" and old["active"]:
            service.store.leave(old["id"])
    if team:
        if not model:
            raise ValueError("--model is required when specifying --team")
        if not any(t["runtime"] == "deepagents" and t["active"] for t in snapshot["teams"]):
            service.join(team, model=model)
    elif model:
        if not any(t["runtime"] == "deepagents" and t["active"] for t in snapshot["teams"]):
            service.auto_teams(model=model)
    else:
        service.ensure_teams()


# ---- main -------------------------------------------------------------------
def serve(service, settings, open_browser=False):
    with service_lock(service.base_root):
        recover_model_work(service)
        initialize(service)
        print(f"JustKernel: http://{settings.lab_host}:{settings.lab_port}/")
        pidfile = service.base_root / "service.pid"
        identity = str(os.getpid())
        pidfile.write_text(identity, encoding="utf-8")
        try:
            if open_browser:
                launch = threading.Timer(
                    1.0, webbrowser.open, args=(f"http://{settings.lab_host}:{settings.lab_port}/",)
                )
                launch.daemon = True
                launch.start()
            uvicorn.run(
                create_lab_app(service),
                host=settings.lab_host,
                port=settings.lab_port,
                access_log=False,
            )
        finally:
            if pidfile.is_file() and pidfile.read_text(encoding="utf-8").strip() == identity:
                pidfile.unlink()


# ---- main -------------------------------------------------------------------
def main():
    args = arguments()
    if args.action == "demo":
        from aworker.lab.dashboard import serve_demo

        serve_demo(args.host or "127.0.0.1", args.port or 4173, args.open_browser)
        return
    overrides = {}
    if args.root is not None:
        overrides["lab_root"] = args.root
    for name in ("host", "port"):
        value = getattr(args, name, None)
        if value is not None:
            overrides["lab_" + name] = value
    settings = Settings(**overrides)
    if args.action == "serve" and args.supervise:
        from aworker.lab.supervisor import supervise

        raise SystemExit(supervise(settings, open_browser=args.open_browser))
    service = LabService(settings)
    action = args.action or "serve"
    if action == "init":
        initialize(service, args.team, args.model)
        print(json.dumps({"ready": True, "operator": service.operator, "harness": "deepagents"}))
    elif action == "serve":
        serve(service, settings, getattr(args, "open_browser", False))
    elif action == "join":
        print(service.join(args.team, model=args.model))
    elif action in {"run", "evaluate"}:

        async def execute():
            try:
                key = service.start_operation(args.team, action, getattr(args, "prompt", ""))
                print(await wait_result(service, key))
            finally:
                await service.close()

        asyncio.run(execute())
    elif action == "leave":
        service.leave(args.team)
    elif action == "snapshot":
        data = service.store.snapshot()
        for job in data["jobs"]:
            job.pop("token", None)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif action == "doctor":
        print(
            json.dumps(
                {
                    "harness": "deepagents",
                    "models": service.registry.catalog(),
                    "npu_configured": service.runner is not None,
                    "langsmith_enabled": settings.lab_langsmith_enabled,
                },
                indent=2,
            )
        )
    elif action == "export":
        target = args.output or service.root / "events.json"
        target.write_text(
            json.dumps(execution_record(service), indent=2),
            encoding="utf-8",
        )
        print(target)
    elif action == "import-inputs":
        snapshot = service.store.snapshot()
        if any(j["state"] in {"running", "queued"} for j in snapshot["jobs"]) or any(
            o["state"] == "running" for o in snapshot["operations"]
        ):
            raise ValueError("finish active work before replacing inputs")
        result = import_input_cases(service.root, args.inputs)
        service.store.event("controller", "task.inputs.updated", **result)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

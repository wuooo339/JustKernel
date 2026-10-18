"""Unified teams, experiments, public artifacts and evidence-linked learning."""

import asyncio
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from aworker.config import Settings
from aworker.lab.continuous import ContinuousSwarm
from aworker.lab.deepagent import DeepAgentRuntime
from aworker.lab.domain import Experience, Specialist, Stage, StageUpdate
from aworker.lab.judger import JudgeMonitor
from aworker.lab.operators import OperatorCatalog
from aworker.lab.policy import PolicyReport, inspect_source
from aworker.lab.prepare import prepare_team
from aworker.lab.project import project_manifest, source_display, source_files, source_identity
from aworker.lab.providers import ModelRegistry
from aworker.lab.runner import RemoteRunner
from aworker.lab.servers import ServerRegistry
from aworker.lab.simulation import Simulator
from aworker.lab.store import LabStore, identifier
from aworker.server.client import send_text_message

DEFAULT_MEMBERS = [
    Specialist(name="analyst", role="analyst"),
    Specialist(name="engineer", role="implementer"),
    Specialist(name="reviewer", role="reviewer"),
]


# ---- LabService -------------------------------------------------------------
class LabService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_root = settings.lab_root.resolve()
        self.catalog = OperatorCatalog(self.base_root, settings.lab_default_operator)
        self.servers = ServerRegistry(settings, self.base_root)
        self.registry = ModelRegistry(settings, vault=self.servers)
        self._operations: dict[str, asyncio.Task] = {}
        self._evaluations: set[asyncio.Task] = set()
        self._team_slots = asyncio.Semaphore(settings.lab_team_concurrency)
        self._bind_workspace(self.catalog.entry(self.catalog.selected())["root"])
        self.simulator = Simulator(self)
        self.judger = JudgeMonitor(self)
        self.swarm = ContinuousSwarm(self)

    # ---- operator and server context ---------------------------------------
    @property
    def operator(self) -> str:
        return json.loads((self.root / "challenge/manifest.json").read_text(encoding="utf-8"))[
            "operator"
        ]

    @property
    def execution_mode(self) -> str:
        path = self.root / "execution-plan.json"
        return (
            json.loads(path.read_text(encoding="utf-8"))["mode"]
            if path.is_file()
            else self.settings.lab_execution_mode
        )

    def set_execution_mode(self, mode: str) -> dict:
        if mode not in {"judge-only", "hybrid"}:
            raise ValueError("unsupported execution mode")
        self.require_idle()
        (self.root / "execution-plan.json").write_text(json.dumps({"mode": mode}), encoding="utf-8")
        self._bind_runner()
        self.store.event("controller", "execution.mode.updated", mode=mode)
        return {"mode": mode}

    def require_idle(self) -> None:
        if hasattr(self, "simulator") and any(
            j["state"] in {"queued", "running"} for j in self.simulator.jobs()
        ):
            raise ValueError("等待当前仿真任务结束后再切换工作区。")
        if hasattr(self, "swarm") and self.swarm.read().get("enabled"):
            raise ValueError("先暂停持续搜索，再切换算子或服务器。")
        if hasattr(self, "judger") and self.judger.automation.selector.status()["running"]:
            raise ValueError("先等待独立候选筛选完成，再切换工作区。")
        if hasattr(self, "judger") and self.judger.automation.busy:
            raise ValueError(
                "wait for the in-flight official submission before switching workspace"
            )
        snapshot = self.store.snapshot()
        if any(o["state"] == "running" for o in snapshot["operations"]) or any(
            j["state"] in {"queued", "running"} for j in snapshot["jobs"]
        ):
            raise ValueError("finish running model/device work before changing operator or server")

    def _bind_workspace(self, root: Path) -> None:
        self.root = root
        self.settings = self.settings.model_copy(update={"lab_root": root})
        self.store = LabStore(root / "journal.sqlite3")
        self._bind_runner()

    def _bind_runner(self) -> None:
        if self.execution_mode == "judge-only":
            self.runner = None
            return
        key = self.servers.data()["active"]
        if not key:
            self.runner = None
            return
        profile = self.servers.get(key)
        settings = self.settings.model_copy(
            update={
                "lab_ssh_host": profile.host,
                "lab_remote_root": profile.remote_root,
                "lab_cann_env": profile.cann_env,
                "lab_device": profile.devices[0],
            }
        )
        expected = [
            ("npu-0" if key == "configured" and i == 0 else f"{key}-npu-{i}", profile.host, i)
            for i in profile.devices
        ]
        current = [(d["id"], d["host"], d["device"]) for d in self.store.snapshot()["devices"]]
        if set(expected) != set(current):
            self.require_idle()
            with self.store.connection() as db:
                db.execute("DELETE FROM devices")
            for name, host, device in expected:
                self.store.register_device(name, host, device)
        adapter = self.root / "challenge/evaluator"
        self.runner = RemoteRunner(
            settings,
            self.store,
            transport=self.servers.transport(key),
            evaluator=adapter if adapter.is_dir() else None,
            register_device=False,
        )

    def select_server(self, key: str) -> dict:
        self.require_idle()
        self.servers.select(key)
        self._bind_runner()
        self.store.event("controller", "server.selected", server=key)
        return {"active": key, "devices": self.store.snapshot()["devices"]}

    def select_operator(self, key: str) -> dict:
        self.require_idle()
        root = self.catalog.entry(key)["root"]
        previous = self.root
        try:
            self._bind_workspace(root)
            self.require_idle()
        except Exception:
            self._bind_workspace(previous)
            raise
        self.catalog.activate(key)
        self.ensure_teams()
        self.store.event("controller", "operator.selected", operator=key)
        return {"operator": key, "teams": self.store.snapshot()["teams"]}

    # ---- team lifecycle -----------------------------------------------------
    def auto_teams(self, count: int = 1, model: str | None = None) -> list[dict]:
        available = [m for m in self.registry.catalog() if m["configured"]]
        if model:
            available = [m for m in available if m["id"] == model]
        if not available:
            raise ValueError("configure a model connection before creating teams")
        profiles = [
            (
                m["id"],
                "gpt" if m["provider"] in {"openai", "chatgpt"} else m["provider"],
            )
            for m in available
        ]
        allocated = self.store.allocate_teams(profiles, count, self.settings.lab_max_teams)
        for name, key in allocated:
            self.join(name, model=key)
        return [{"team": name, "model": key, "runtime": "deepagents"} for name, key in allocated]

    def ensure_teams(self) -> None:
        configured = {m["id"] for m in self.registry.catalog() if m["configured"]}
        teams = self.store.snapshot()["teams"]
        if not configured or any(
            t["active"] and t["runtime"] == "deepagents" and t["model"] in configured for t in teams
        ):
            return
        capacity = self.settings.lab_max_teams - sum(bool(t["active"]) for t in teams)
        if capacity > 0:
            self.auto_teams(min(len(configured), capacity))

    def join(self, team: str, runtime: str = "deepagents", model: str | None = None) -> Path:
        identifier(team)
        if runtime != "deepagents":
            raise ValueError("only the unified deepagents harness is supported")
        if not model or model not in self.registry.profiles:
            raise ValueError("select an existing model profile")
        active = [
            t for t in self.store.snapshot()["teams"] if t["active"] and t["runtime"] == runtime
        ]
        if team not in {t["id"] for t in active} and len(active) >= self.settings.lab_max_teams:
            raise ValueError("team capacity reached")
        self.store.join(team, runtime, model)
        folder = prepare_team(self.root, team)
        if not any(m["team"] == team for m in self.store.snapshot()["members"]):
            self.set_members(team, DEFAULT_MEMBERS)
        return folder

    def set_members(self, team: str, members: list[Specialist]) -> None:
        self.team_folder(team)
        if not members or len(members) > self.settings.max_members:
            raise ValueError("team roster must contain 1–max_members specialists")
        if len({m.name for m in members}) != len(members):
            raise ValueError("specialist names must be unique")
        if any(m.model and m.model not in self.registry.profiles for m in members):
            raise ValueError("specialist model profile does not exist")
        self.store.set_members(team, [m.model_dump() for m in members])

    def team_folder(self, team: str) -> Path:
        identifier(team)
        entry = next((t for t in self.store.snapshot()["teams"] if t["id"] == team), None)
        if not entry or not entry["active"] or entry["runtime"] != "deepagents":
            raise ValueError("team is not an active unified Deep Agents team")
        return self.root / "teams" / team

    def candidate(self, team: str) -> dict:
        manifest = project_manifest(self.root)
        files = source_files(self.root, self.team_folder(team))
        return {
            "team": team,
            "source": source_display(files, manifest.get("editable_paths")),
            "files": files,
            "sha256": source_identity(files),
        }

    def reset_operators(self, keep: str) -> dict:
        self.require_idle()
        self.catalog.entry(keep)
        archived = [r["id"] for r in self.catalog.catalog(include_archived=True) if r["id"] != keep]
        result = self.select_operator(keep)
        (self.base_root / "archived-operators.json").write_text(
            json.dumps(archived), encoding="utf-8"
        )
        self.store.event("controller", "operators.archived", archived=archived, kept=keep)
        return result | {"archived": archived}

    def leave(self, team: str) -> None:
        self.team_folder(team)
        if any(
            o["team"] == team and o["state"] == "running"
            for o in self.store.snapshot()["operations"]
        ):
            raise ValueError("finish the current operation before leaving")
        self.store.leave(team)

    # ---- task lifecycle -----------------------------------------------------
    def start_operation(self, team: str, kind: str, prompt: str = "") -> str:
        self.team_folder(team)
        if kind not in {"run", "evaluate"}:
            raise ValueError("unsupported operation")
        if kind == "run" and not prompt.strip():
            raise ValueError("a task prompt is required")
        if kind == "evaluate" and self.runner is None:
            raise ValueError("no physical NPU is configured")
        key = uuid4().hex
        self.store.operation(key, team, kind)
        self.store.event(
            team, "control.started", operation_id=key, action=kind, harness="deepagents"
        )
        self._operations[key] = asyncio.create_task(
            self._execute_operation(key, team, kind, prompt)
        )
        return key

    def start_swarm(self, teams: list[str], prompt: str) -> dict:
        if not teams or len(set(teams)) != len(teams) or len(teams) > self.settings.lab_max_teams:
            raise ValueError("select 1–100 distinct active teams")
        configured = {m["id"] for m in self.registry.catalog() if m["configured"]}
        snapshot = self.store.snapshot()
        for name in teams:
            self.team_folder(name)
            row = next(t for t in snapshot["teams"] if t["id"] == name)
            if row["model"] not in configured:
                raise ValueError("team model is not configured: " + name)
            if any(o["team"] == name and o["state"] == "running" for o in snapshot["operations"]):
                raise ValueError("team already has an active operation: " + name)
        if not prompt.strip():
            raise ValueError("a task prompt is required")
        directions = [
            "Prioritize a clear general implementation and correctness before optimization.",
            "Prioritize general row reduction and tail-safe vectorization.",
            "Prioritize general column reduction and legal in-kernel synchronization.",
            "Prioritize full reduction, FLOAT32 accumulation and single-launch correctness.",
            "Prioritize metadata validation, output shapes and robust InferShape/Tiling.",
            "Prioritize input1 reuse, UB capacity and memory traffic analysis.",
            "Prioritize numerical error, FP16 casts and reduction stability.",
            "Prioritize a different general tiling design and independent source review.",
        ]
        operations = [
            {
                "team": name,
                "operation_id": self.start_operation(
                    name, "run", prompt + "\nTeam focus: " + directions[i % len(directions)]
                ),
            }
            for i, name in enumerate(teams)
        ]
        self.store.event(
            "controller",
            "swarm.started",
            teams=teams,
            concurrency=self.settings.lab_team_concurrency,
        )
        return {"operations": operations, "concurrency": self.settings.lab_team_concurrency}

    async def _execute_operation(self, key: str, team: str, kind: str, prompt: str):
        try:
            if kind == "run":
                answer = await self.run_team(team, prompt, key)
                success = True
            else:
                answer = await self.evaluate(team, key)
                success = answer["pass"]
            state = "completed" if success else "failed"
            self.store.operation_finished(
                key, state, None if success else "correctness check failed"
            )
            self.store.event(team, "control." + state, operation_id=key, result=answer)
        except asyncio.CancelledError:
            self.store.operation_finished(key, "cancelled")
            self.store.event(team, "control.cancelled", operation_id=key)
        except Exception as exc:
            message = self.redact(str(exc))[:4000]
            self.store.operation_finished(key, "failed", message)
            self.store.event(team, "control.failed", operation_id=key, message=message)
        finally:
            self._operations.pop(key, None)
            self.swarm.wake.set()

    async def run_team(self, team: str, prompt: str, run_id: str | None = None) -> str:
        self.team_folder(team)
        key = run_id or uuid4().hex
        self.store.event(team, "model.slot.waiting", run_id=key)
        async with self._team_slots:
            self.store.event(team, "model.slot.acquired", run_id=key)
            try:
                return await DeepAgentRuntime(self, team, key).run(prompt)
            finally:
                self.store.event(team, "model.slot.released", run_id=key)

    def cancel_operation(self, key: str):
        entry = next((o for o in self.store.snapshot()["operations"] if o["id"] == key), None)
        if not entry or entry["state"] != "running" or key not in self._operations:
            raise ValueError("operation is not running in this service")
        if entry["kind"] != "run":
            raise ValueError("a physical experiment keeps its lease until it finishes")
        self._operations[key].cancel()

    async def close(self):
        await self.swarm.close()
        await self.judger.close()
        if hasattr(self, "setup_jobs"):
            await self.setup_jobs.close()
        for key in list(self._operations):
            operation = next(o for o in self.store.snapshot()["operations"] if o["id"] == key)
            if operation["kind"] == "run":
                self._operations[key].cancel()
        await asyncio.gather(*self._operations.values(), return_exceptions=True)
        await self.simulator.close()
        if self._evaluations:
            await asyncio.gather(*self._evaluations, return_exceptions=True)

    # ---- policy and trusted device queue ------------------------------------
    def inspect_policy(self, team: str, run_id: str | None = None) -> PolicyReport:
        candidate = self.candidate(team)
        report = inspect_source(
            candidate["source"], project_manifest(self.root).get("entrypoint", "run_kernel")
        )
        report.source_sha256 = candidate["sha256"]
        self.store.stage(
            team,
            StageUpdate(
                stage=Stage.POLICY,
                state="completed" if report.automated_pass else "failed",
                message="Automated source checks; source/physical trace review still required",
                run_id=run_id,
                evidence=report.source_sha256,
            ),
        )
        self.store.event(team, "policy.checked", run_id=run_id, **report.model_dump())
        return report

    async def evaluate(self, team: str, run_id: str | None = None) -> dict:
        if self.runner is None:
            raise ValueError("no physical NPU configured")
        manifest = json.loads((self.root / "challenge/manifest.json").read_text(encoding="utf-8"))
        if not manifest.get("adapter_ready", self.operator == "RotaryPosEmb"):
            raise ValueError(
                "this operator needs its own completed and reviewed evaluator before NPU evaluation"
            )
        report = self.inspect_policy(team, run_id)
        if not report.automated_pass:
            raise ValueError("automated policy checks failed; inspect the findings")
        source = (self.team_folder(team) / "kernel.asc").read_bytes().decode("utf-8")
        task = asyncio.create_task(asyncio.to_thread(self.runner.evaluate, team, source, run_id))
        self._evaluations.add(task)
        task.add_done_callback(self._evaluations.discard)
        return await asyncio.shield(task)

    # ---- public results and conditional learning ----------------------------
    def _current_passing(self, team: str) -> tuple[bytes, dict]:
        candidate = self.candidate(team)
        source = candidate["source"].encode("utf-8")
        digest = candidate["sha256"]
        case_digest = hashlib.sha256(
            (self.root / "challenge" / "cases.json").read_bytes()
        ).hexdigest()
        matches, cursor = [], 0
        while batch := self.store.events(cursor):
            matches.extend(
                e["data"]
                for e in batch
                if e["team"] == team
                and e["kind"] == "evaluation.completed"
                and e["data"].get("pass")
                and e["data"].get("source_sha256") == digest
                and e["data"].get("case_pack_sha256") == case_digest
            )
            cursor = batch[-1]["seq"]
        if not matches:
            raise ValueError("current source/input pack has no passing real NPU evaluation")
        return source, matches[-1]

    def publish(self, team: str, run_id: str | None = None) -> dict:
        source, result = self._current_passing(team)
        key = hashlib.sha256(
            (result["source_sha256"] + result["case_pack_sha256"]).encode()
        ).hexdigest()
        folder = self.root / "public" / key
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "result.json").exists():
            (folder / "kernel.asc").write_bytes(source)
            (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        self.store.stage(
            team,
            StageUpdate(
                stage=Stage.SHARE,
                state="completed",
                message="Published an exact-source/input-pack passing result",
                run_id=run_id,
                evidence=key,
            ),
        )
        self.store.event(
            team,
            "artifact.published",
            artifact_id=key,
            sha256=result["source_sha256"],
            run_id=run_id,
            case_pack_sha256=result["case_pack_sha256"],
        )
        return {"artifact_id": key, "sha256": result["source_sha256"], "result": result}

    def public(self, include_source: bool = True) -> list[dict]:
        results = []
        for path in sorted((self.root / "public").glob("*/result.json")):
            result = json.loads(path.read_text(encoding="utf-8"))
            row = {
                "artifact_id": path.parent.name,
                "sha256": result["source_sha256"],
                "result": result,
            }
            if include_source:
                row["source"] = (path.parent / "kernel.asc").read_text(encoding="utf-8")
            timings = [
                c.get("measurement", {}).get("event_mean_us") for c in result.get("cases", [])
            ]
            row["geomean_us"] = (
                math.exp(sum(math.log(t) for t in timings) / len(timings))
                if timings and all(t and t > 0 for t in timings)
                else None
            )
            results.append(row)
        return results

    def public_code(self, artifact: str) -> str:
        if len(artifact) != 64 or any(c not in "0123456789abcdef" for c in artifact):
            raise ValueError("invalid artifact identity")
        return (self.root / "public" / artifact / "kernel.asc").read_text(encoding="utf-8")

    def record_experience(self, team: str, run_id: str, experience: Experience) -> str:
        if experience.scope not in {self.operator, "transfer-hypothesis"}:
            raise ValueError(
                "experience scope must match the current operator or be a transfer hypothesis"
            )
        _, result = self._current_passing(team)
        if result["job_id"] != experience.evidence_job:
            raise ValueError("experience must cite the current code's passed evidence job")
        data = experience.model_dump()
        data.update(
            source_sha256=result["source_sha256"],
            case_pack_sha256=result["case_pack_sha256"],
            verified="local-correctness",
            timing_protocol=result.get("timing"),
        )
        key = self.store.experience(team, data)
        self.store.stage(
            team,
            StageUpdate(
                stage=Stage.DISTILL,
                state="completed",
                message=experience.title,
                run_id=run_id,
                evidence=key,
            ),
        )
        return key

    def redact(self, message: str) -> str:
        for secret in [
            *self.settings.lab_provider_keys.values(),
            *self.registry.local_keys.values(),
        ]:
            message = message.replace(secret.get_secret_value(), "[redacted]")
        return message

    # ---- A2A inter-team transport ------------------------------------------
    async def send_notice(self, notice):
        endpoint = f"http://{self.settings.lab_host}:{self.settings.lab_port}/a2a/"
        return await send_text_message(
            endpoint,
            json.dumps(
                {
                    "action": "message",
                    "team": "judger",
                    "recipient": notice.recipient,
                    "message": notice.message,
                    "artifact": notice.artifact,
                    "delivery_id": notice.id,
                }
            ),
        )

    async def send_message(
        self, team: str, recipient: str, message: str, artifact: str | None = None
    ) -> str:
        self.team_folder(team)
        self.team_folder(recipient)
        endpoint = f"http://{self.settings.lab_host}:{self.settings.lab_port}/a2a/"
        return await send_text_message(
            endpoint,
            json.dumps(
                {
                    "action": "message",
                    "team": team,
                    "recipient": recipient,
                    "message": message,
                    "artifact": artifact,
                }
            ),
        )

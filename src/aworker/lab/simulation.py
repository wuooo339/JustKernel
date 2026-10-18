"""Independent source/input-bound experiments through a local Linux CANN worker."""

import asyncio
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from aworker.lab.domain import Stage, StageUpdate


# ---- SimulationRequest ------------------------------------------------------
class SimulationRequest(BaseModel):
    schema_version: str = Field(default="justkernel.simulation.request.v1", alias="schema")
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    workspace_id: str
    team: str
    operator: str
    files: dict[str, str]
    source_sha256: str
    case_pack_sha256: str
    cases_json: str
    case_ids: list[str] = Field(min_length=1, max_length=100)
    target_soc: str = "Ascend910B4"
    worker_sha256: str
    hypothesis: str = Field(max_length=6000)
    learned_from: list[str] = Field(default_factory=list, max_length=30)
    timeout_seconds: int = Field(default=1800, ge=30, le=3600)
    created_at: float
    evaluation_mode: Literal["full-profile", "functional-then-profile"] = "full-profile"
    profile_case_ids: list[str] = Field(default_factory=list, max_length=100)


# ---- Simulator --------------------------------------------------------------
class Simulator:
    def __init__(self, service):
        self.service = service
        self.spool = service.base_root / "simulator"
        self.pending = set()
        self.team_locks = {}
        self.observer = None

    # ---- replayable progress survives model cancellation/service restart -----
    async def start(self):
        if self.observer is None or self.observer.done():
            self.observer = asyncio.create_task(self.observe())

    async def close(self):
        tasks = [*self.pending, *([self.observer] if self.observer else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.observer = None

    async def observe(self):
        while True:
            try:
                path = self.service.root / "simulation-projection.json"
                seen = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
                changed = False
                capability = self.status()
                worker = capability.get("worker") or {}
                worker_key = json.dumps(
                    [
                        capability["available"],
                        capability["state"],
                        worker.get("worker_id"),
                        worker.get("job_id"),
                    ]
                )
                if seen.get("__worker__") != worker_key:
                    seen["__worker__"] = worker_key
                    changed = True
                    self.service.store.event(
                        "controller",
                        "simulation.worker.updated",
                        available=capability["available"],
                        state=capability["state"],
                        target_soc=capability["target_soc"],
                        message=capability["message"],
                    )
                rows = self.jobs()
                current = self.current_experiments(rows)
                for row in reversed(rows):
                    selected = current[row["team"]]["id"] == row["id"]
                    key = json.dumps(
                        [row["state"], row.get("phase"), len(row.get("cases", [])), selected]
                    )
                    if seen.get(row["id"]) == key:
                        continue
                    seen[row["id"]] = key
                    changed = True
                    cases = row.get("cases", [])
                    self.service.store.event(
                        row["team"],
                        "simulation.status.updated",
                        job_id=row["id"],
                        state=row["state"],
                        phase=row.get("phase"),
                        source_sha256=row["source_sha256"],
                        completed_cases=len(cases),
                        passed_cases=sum(c.get("pass") is True for c in cases),
                        requested_cases=len(row["case_ids"]),
                        error=row.get("error"),
                    )
                    if not selected:
                        continue
                    stage = Stage.QUEUE if row["state"] == "queued" else Stage.EXECUTE
                    state = "started" if row["state"] == "queued" else "progress"
                    if row["state"] in {"completed", "failed", "cancelled"}:
                        stage = Stage.VERIFY
                        state = (
                            "completed"
                            if row["state"] == "completed"
                            else ("skipped" if row["state"] == "cancelled" else "failed")
                        )
                    self.service.store.stage(
                        row["team"],
                        StageUpdate(
                            stage=stage,
                            state=state,
                            message="910B4 仿真 · " + str(row.get("phase") or row["state"]),
                            evidence=row["id"],
                        ),
                    )
                if changed:
                    temporary = path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(seen), encoding="utf-8")
                    temporary.replace(path)
            except Exception as error:
                self.service.store.event(
                    "simulator",
                    "simulation.observer.error",
                    message=self.service.redact(str(error))[:500],
                )
            await asyncio.sleep(2)

    # ---- active work takes precedence over newer obsolete queue entries ------
    @staticmethod
    def current_experiments(rows):
        current = {}
        priority = {"running": 3, "queued": 2, "cancelled": 0}

        def order(row):
            return priority.get(row["state"], 1), row.get("created_at", 0)

        for row in rows:
            previous = current.get(row["team"])
            if previous is None or order(row) > order(previous):
                current[row["team"]] = row
        return current

    # ---- capability and immutable receipt identity --------------------------
    @property
    def required(self):
        return self.service.settings.lab_require_simulation

    @property
    def workspace_id(self):
        return hashlib.sha256(str(self.service.root.resolve()).encode()).hexdigest()

    def identity(self):
        folder = Path(__file__).parent / "resources/simulator"
        return hashlib.sha256(
            b"".join(
                (folder / name).read_bytes()
                for name in ["worker.py", "runner.cpp", "CMakeLists.txt"]
            )
        ).hexdigest()

    def status(self):
        path = self.spool / "heartbeat.json"
        try:
            worker = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A Windows/WSL reader can race atomic replacement; retry next heartbeat.
            worker = {}
        ready = (
            worker.get("schema") == "justkernel.simulator.worker.v1"
            and worker.get("state") in {"ready", "busy"}
            and worker.get("worker_sha256") == self.identity()
            and worker.get("target_soc") == "Ascend910B4"
            and isinstance(worker.get("at"), (int, float))
            and -5 <= time.time() - worker["at"] < 30
        )
        return {
            "available": bool(ready),
            "required": self.required,
            "state": worker.get("state", "not-configured") if ready else "unavailable",
            "target_soc": "Ascend910B4",
            "concurrency": worker.get("concurrency", 1) if ready else 0,
            "profiling_concurrency": worker.get("profiling_concurrency", 1) if ready else 0,
            "active_jobs": worker.get("active_jobs", []) if ready else [],
            "worker": worker if ready else None,
            "message": (
                f"{worker.get('concurrency', 1)} 个并行实验槽 · "
                f"{worker.get('profiling_concurrency', 1)} 个独占性能采集槽"
            )
            if ready
            else "等待本机 Linux/CANN 仿真 Worker",
        }

    def jobs(self, team=None):
        rows = []
        for path in self.spool.glob("jobs/*/request.json"):
            request = json.loads(path.read_text(encoding="utf-8"))
            if request.get("workspace_id") != self.workspace_id or team and request["team"] != team:
                continue
            result = path.with_name("result.json")
            row = (
                json.loads(result.read_text(encoding="utf-8"))
                if result.is_file()
                else {
                    "id": request["id"],
                    "team": request["team"],
                    "state": "queued",
                    "source_sha256": request["source_sha256"],
                    "case_pack_sha256": request["case_pack_sha256"],
                }
            )
            row.setdefault("case_ids", request["case_ids"])
            row.setdefault("worker_sha256", request["worker_sha256"])
            row["hypothesis"] = request["hypothesis"]
            row["learned_from"] = request.get("learned_from", [])
            row["created_at"] = request["created_at"]
            rows.append(row)
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def evidence(self, team, digest, case_hash=None, require_coverage=False):
        if case_hash is None:
            case_hash = hashlib.sha256(
                (self.service.root / "challenge/cases.json").read_bytes()
            ).hexdigest()
        for row in self.jobs(team):
            if (
                row.get("schema") == "justkernel.simulation.v1"
                and row.get("source") == "cann-simulator"
                and row.get("state") == "completed"
                and row.get("functional_pass") is True
                and row.get("source_sha256") == digest
                and row.get("case_pack_sha256") == case_hash
                and row.get("worker_sha256") == self.identity()
                and row.get("cases")
                and all(c.get("pass") is True for c in row["cases"])
            ):
                request = self.spool / "jobs" / row["id"] / "request.json"
                if row.get("request_sha256") == hashlib.sha256(request.read_bytes()).hexdigest():
                    payload = json.loads(request.read_text(encoding="utf-8"))
                    mode = payload.get("evaluation_mode", "full-profile")
                    if mode == "functional-then-profile":
                        profiles = set(payload.get("profile_case_ids", []))
                        observed_profiles = {
                            c["id"]
                            for c in row["cases"]
                            if c.get("profile_pass") is True and c.get("profiling_files")
                        }
                        if (
                            row.get("evaluation_mode") != mode
                            or row.get("reference")
                            != {
                                "engine": "pytorch-cpu-fp32-v1",
                                "version": "2.14.1+cpu",
                                "threads": 1,
                            }
                            or any(
                                c.get("validation_kind") != "functional-pvmodel"
                                for c in row["cases"]
                            )
                            or not profiles <= observed_profiles
                            or (require_coverage and not set(self.profile_cases()) <= profiles)
                        ):
                            continue
                    elif mode != "full-profile" or any(
                        not c.get("profiling_files") for c in row["cases"]
                    ):
                        continue
                    if (
                        payload["team"] == team
                        and payload["source_sha256"] == digest
                        and payload["case_pack_sha256"] == case_hash
                        and payload["worker_sha256"] == self.identity()
                        and row.get("target_soc") == payload["target_soc"]
                        and len(row["cases"]) == len(payload["case_ids"])
                        and {c["id"] for c in row["cases"]} == set(payload["case_ids"])
                        and (
                            not require_coverage
                            or set(self.default_cases()) <= set(payload["case_ids"])
                        )
                    ):
                        return row
        return None

    def default_cases(self):
        cases = json.loads((self.service.root / "challenge/cases.json").read_text(encoding="utf-8"))
        return [c["id"] for c in cases]

    # ---- fixed representative set, independent of team code or output ---------
    def profile_cases(self):
        cases = json.loads((self.service.root / "challenge/cases.json").read_text(encoding="utf-8"))
        selected = {}
        for case in sorted(cases, key=lambda c: math.prod(c["shape"])):
            axes = tuple(sorted({int(a) % len(case["shape"]) for a in case["axis"]}))
            selected.setdefault(axes, case["id"])
        return list(selected.values())

    def can_learn(self, team):
        return not self.required or any(
            self.evidence(team, row["source_sha256"], row.get("case_pack_sha256"))
            for row in self.jobs(team)
            if row.get("state") == "completed"
        )

    def require_learning(self, team):
        if not self.can_learn(team):
            raise ValueError("先完成本队独立仿真实验，再学习其他队；借鉴后的源码仍须本队重新仿真。")

    def logs(self, key, team=None):
        row = next((r for r in self.jobs(team) if r["id"] == key), None)
        if row is None:
            raise ValueError("simulation job does not belong to this workspace/team")
        path = self.spool / "jobs" / key / "execution.log"
        return {
            "job": row,
            "log_tail": self.service.redact(
                path.read_text(encoding="utf-8", errors="replace")[-24000:]
                if path.is_file()
                else ""
            ),
        }

    # ---- cancel only unclaimed queue entries; never stop a running child ------
    def cancel_queued(self, key, team, reason):
        row = next((r for r in self.jobs(team) if r["id"] == key), None)
        if row is None or row["state"] != "queued":
            return False
        folder = self.spool / "jobs" / key
        request_path = folder / "request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        result = {
            k: request[k]
            for k in [
                "id",
                "workspace_id",
                "team",
                "operator",
                "source_sha256",
                "case_pack_sha256",
                "case_ids",
                "target_soc",
                "worker_sha256",
            ]
        }
        result.update(
            schema="justkernel.simulation.v1",
            source="controller",
            state="cancelled",
            phase="cancelled-before-execution",
            functional_pass=False,
            cases=[],
            request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
            finished_at=time.time(),
            reason=reason,
        )
        temporary = folder / (uuid4().hex + ".cancel.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        try:
            # Exclusive atomic commit cannot overwrite a claimed/running/finished record.
            # If the worker was already claiming this entry, its authoritative result wins.
            os.link(temporary, folder / "result.json")
        except FileExistsError:
            return False
        finally:
            temporary.unlink()
        self.service.store.event(team, "simulation.queue.cancelled", job_id=key, reason=reason)
        return True

    # ---- every team submits and receives its own experiment ------------------
    async def evaluate(self, team, run_id, hypothesis="", case_ids=None, learned_from=None):
        if not self.status()["available"]:
            result = {
                "state": "unavailable",
                "reason": self.status()["message"],
                "cycles": None,
                "npu_latency_us": None,
                "official_score": None,
            }
            self.service.store.event(team, "simulation.unavailable", run_id=run_id, **result)
            return result
        lock = self.team_locks.setdefault(team, asyncio.Lock())
        async with lock:
            task = asyncio.create_task(
                self._experiment(team, run_id, hypothesis, case_ids, learned_from)
            )
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)
            return await asyncio.shield(task)

    async def _experiment(self, team, run_id, hypothesis, case_ids, learned_from):
        candidate = self.service.candidate(team)
        policy = self.service.inspect_policy(team, run_id)
        if not policy.automated_pass:
            return {"state": "blocked", "error": "修正源码规则检查发现的问题后再仿真。"}
        cases_text = (self.service.root / "challenge/cases.json").read_bytes().decode()
        cases = json.loads(cases_text)
        known = {c["id"] for c in cases}
        selected = case_ids or self.default_cases()
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= known:
            raise ValueError("select distinct IDs from the trusted local input pack")
        case_hash = hashlib.sha256(cases_text.encode()).hexdigest()
        pending = next(
            (
                row
                for row in self.jobs(team)
                if row["state"] in {"queued", "running"}
                and row["source_sha256"] == candidate["sha256"]
                and row["case_pack_sha256"] == case_hash
                and row["worker_sha256"] == self.identity()
                and set(row["case_ids"]) == set(selected)
            ),
            None,
        )
        if pending:
            key = pending["id"]
            folder = self.spool / "jobs" / key
            request = SimulationRequest.model_validate_json((folder / "request.json").read_bytes())
        else:
            prior_pending = next(
                (r for r in self.jobs(team) if r["state"] in {"queued", "running"}), None
            )
            if prior_pending:
                return {
                    "state": "waiting-previous-experiment",
                    "job_id": prior_pending["id"],
                    "message": "先等待本队已提交的独立实验，读取反馈后再提交新版本；不要重复排队。",
                }
            key = uuid4().hex
            request = SimulationRequest(
                id=key,
                workspace_id=self.workspace_id,
                team=team,
                operator=self.service.operator,
                files=candidate["files"],
                source_sha256=candidate["sha256"],
                case_pack_sha256=case_hash,
                cases_json=cases_text,
                case_ids=selected,
                worker_sha256=self.identity(),
                hypothesis=hypothesis,
                learned_from=learned_from or [],
                created_at=time.time(),
                evaluation_mode="functional-then-profile",
                profile_case_ids=[c for c in self.profile_cases() if c in selected],
            )
            folder = self.spool / "jobs" / key
            folder.mkdir(parents=True)
            temporary = folder / "request.tmp"
            temporary.write_text(request.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
            temporary.replace(folder / "request.json")
        self.service.store.event(
            team,
            "simulation.queued",
            run_id=run_id,
            job_id=key,
            source_sha256=candidate["sha256"],
            case_ids=selected,
        )
        deadline = time.monotonic() + request.timeout_seconds + 3600
        prior = None
        offline_since = None
        while time.monotonic() < deadline:
            result_path = folder / "result.json"
            if result_path.is_file():
                result = json.loads(result_path.read_text(encoding="utf-8"))
                phase = (result["state"], result.get("phase"), len(result.get("cases", [])))
                if phase != prior:
                    self.service.store.event(
                        team,
                        "simulation.phase",
                        run_id=run_id,
                        job_id=key,
                        state=result["state"],
                        phase=result.get("phase"),
                    )
                    prior = phase
                if result["state"] in {"completed", "failed", "cancelled"}:
                    if (
                        result.get("request_sha256")
                        != hashlib.sha256((folder / "request.json").read_bytes()).hexdigest()
                    ):
                        raise ValueError("simulation receipt does not match its immutable request")
                    self.service.store.event(
                        team,
                        "simulation." + result["state"],
                        run_id=run_id,
                        job_id=key,
                        result=result,
                    )
                    return self.logs(key, team)
            if not self.status()["available"]:
                offline_since = offline_since or time.monotonic()
                if time.monotonic() - offline_since > 30:
                    self.service.store.event(
                        team, "simulation.worker.waiting", run_id=run_id, job_id=key
                    )
                    return {
                        "state": "waiting-worker",
                        "job_id": key,
                        "message": "仿真 Worker 不在线；已提交任务保留，禁止宣称通过。",
                    }
            else:
                offline_since = None
            await asyncio.sleep(2)
        return {"state": "waiting", "job_id": key, "message": "队列等待超时，后台任务及记录保留。"}

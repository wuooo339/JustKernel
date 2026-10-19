"""Independent, continuously replenished model work; never waits for official judging."""

import asyncio
import contextlib
import json
import time
from typing import Literal

from pydantic import BaseModel, Field


# ---- SwarmPlan --------------------------------------------------------------
class SwarmPlan(BaseModel):
    enabled: bool = False
    strategy: Literal["baseline", "parallel"] = "baseline"
    main_team: str | None = None
    model: str | None = None
    teams: list[str] | None = None
    prompt: str = Field(default="持续优化当前算子，学习公开候选和真实反馈。", max_length=100000)
    max_turns: int | None = Field(default=None, ge=1, le=100000)
    turn_interval: int = Field(default=15, ge=5, le=3600)


# ---- ContinuousSwarm --------------------------------------------------------
class ContinuousSwarm:
    def __init__(self, service):
        self.service = service
        self.task = None
        self.wake = asyncio.Event()
        self.stopping = False

    # ---- per-operator durable plan; no work starts during construction -------
    def read(self):
        path = self.service.root / "swarm.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def write(self, data):
        path = self.service.root / "swarm.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def status(self):
        data = self.read()
        waiting = (
            self.service.simulator.required and not self.service.simulator.status()["available"]
        )
        return {
            **SwarmPlan.model_validate(data).model_dump(),
            "progress": data.get("progress", {}),
            "waiting_for": "simulator" if data.get("enabled") and waiting else None,
            "blocked_reason": data.get("blocked_reason"),
        }

    async def configure(self, plan: SwarmPlan):
        if plan.strategy == "baseline":
            teams = self.service.store.snapshot()["teams"]
            selected = [t for t in teams if t["active"] and t["runtime"] == "deepagents"]
            main = plan.main_team or (plan.teams[0] if plan.teams else None)
            if main is None and selected:
                main = selected[0]["id"]
            if main is not None:
                if main not in {t["id"] for t in selected}:
                    raise ValueError("选择一个活动团队作为主队。")
                plan = plan.model_copy(update={"main_team": main, "teams": [main]})
                if plan.enabled and plan.model:
                    self.service.rebind_model(main, plan.model)
        if plan.enabled:
            configured = {m["id"] for m in self.service.registry.catalog() if m["configured"]}
            teams = self.service.store.snapshot()["teams"]
            selected = [
                t for t in teams if t["active"] and (plan.teams is None or t["id"] in plan.teams)
            ]
            if not selected or (
                plan.teams is not None and {t["id"] for t in selected} != set(plan.teams)
            ):
                raise ValueError("先选择已登记的活动团队。")
            if any(t["model"] not in configured for t in selected):
                raise ValueError("所选团队尚未配置模型。")
        data = self.read()
        data.update(plan.model_dump())
        if plan.enabled:
            data.pop("blocked_reason", None)
            for name, state in data.get("progress", {}).items():
                if plan.teams is None or name in plan.teams:
                    state["next_at"] = 0
                    state["credential_failure"] = state.get("operation_id")
                    state["observed"] = state.get("operation_id")
                    state["failures"] = 0
        self.write(data)
        self.service.store.event("controller", "swarm.continuous.configured", **plan.model_dump())
        self.wake.set()
        if plan.enabled:
            await self.start()
        return self.status()

    async def start(self):
        if self.read().get("enabled") and (self.task is None or self.task.done()):
            self.stopping = False
            self.task = asyncio.create_task(self.loop())

    async def close(self):
        self.stopping = True
        self.wake.set()
        if self.task:
            await self.task
            self.task = None

    # ---- each team advances as soon as its own bounded turn finishes ---------
    async def loop(self):
        while not self.stopping and self.read().get("enabled"):
            self.wake.clear()
            try:
                self.tick()
            except Exception as exc:
                self.service.store.event(
                    "controller",
                    "swarm.continuous.error",
                    message=self.service.redact(str(exc))[:500],
                )
            if self.stopping or not self.read().get("enabled"):
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), 5)

    def tick(self):
        data = self.read()
        if not data.get("enabled"):
            return
        plan = SwarmPlan.model_validate(data)
        progress = data.setdefault("progress", {})
        snapshot = self.service.store.snapshot()
        operations = {o["id"]: o for o in snapshot["operations"]}
        active = {o["team"] for o in operations.values() if o["state"] == "running"}
        configured = {m["id"] for m in self.service.registry.catalog() if m["configured"]}
        selected = [
            t
            for t in snapshot["teams"]
            if t["active"]
            and t["runtime"] == "deepagents"
            and (plan.teams is None or t["id"] in plan.teams)
        ]
        if plan.strategy == "baseline":
            selected = (
                [t for t in selected if t["id"] == plan.main_team]
                if plan.main_team
                else selected[:1]
            )
        selected_ids = {t["id"] for t in selected}
        # Authentication/billing failures require a user action, not repeated paid turns.
        for state in progress.values():
            prior = operations.get(state.get("operation_id"))
            error = str((prior or {}).get("error") or "").lower()
            if (
                prior
                and prior["team"] in selected_ids
                and prior["state"] == "failed"
                and state.get("credential_failure") != prior["id"]
                and any(
                    marker in error
                    for marker in (
                        "insufficient balance",
                        "invalid api key",
                        "incorrect api key",
                        "error code: 402",
                        "error code: 401",
                    )
                )
            ):
                data.update(
                    enabled=False, blocked_reason="模型额度或认证失败，请修复连接并测试后重新启动。"
                )
                state["credential_failure"] = prior["id"]
                self.write(data)
                self.service.store.event(
                    "controller",
                    "swarm.blocked.model",
                    affected_team=prior["team"],
                    message=data["blocked_reason"],
                )
                return
        for team in snapshot["teams"]:
            name = team["id"]
            if (
                not team["active"]
                or team["runtime"] != "deepagents"
                or team["model"] not in configured
            ):
                continue
            if name not in selected_ids:
                continue
            state = progress.setdefault(name, {"turns": 0, "failures": 0})
            prior = operations.get(state.get("operation_id"))
            if prior and prior["state"] != "running" and state.get("observed") != prior["id"]:
                state["observed"] = prior["id"]
                failed = prior["state"] != "completed"
                state["failures"] = min(8, state.get("failures", 0) + 1) if failed else 0
                state["next_at"] = time.time() + (
                    min(600, 30 * 2 ** (state["failures"] - 1)) if failed else plan.turn_interval
                )
                # A completed source turn may have omitted its explicit staging call.
                if not failed:
                    with contextlib.suppress(ValueError, OSError):
                        self.service.judger.stage(name)
            if name in active or time.time() < state.get("next_at", 0):
                continue
            if plan.max_turns is not None and state["turns"] >= plan.max_turns:
                continue
            if self.service.simulator.required and any(
                j["state"] in {"queued", "running"} for j in self.service.simulator.jobs(name)
            ):
                state["phase"] = "awaiting-own-experiment"
                continue
            if self.service.simulator.required and not self.service.simulator.status()["available"]:
                if state.get("phase") != "waiting-simulator":
                    state["phase"] = "waiting-simulator"
                    self.service.store.event(name, "swarm.waiting.simulator")
                continue
            prompt = plan.prompt + (
                "\n持续蜂群第 " + str(state["turns"] + 1) + " 轮。"
                "先 read_simulation_results 阅读本队实际实验，独立提出假设并实施。"
                "调用 simulate_kernel 编译和仿真本队代码；根据实际诊断修正后重新实验。"
                "本队完成独立仿真后再 read_team_messages、read_judge_status，"
                "学习公开候选，借鉴后的改动必须在本队重新仿真。"
                "团队独立维护代码；不要等待其他团队或官测结束。"
                "保留已有改进，不重置或回退为空工程。"
                "完成一个实质改动后由 reviewer 复核实际 SHA，queue_official_test 提出冻结候选，"
                "写清改动依据与未知项。候选池交给独立筛选器，仅精选挑战版本送官测。"
                "本轮结束后调度器会继续派下一轮；不要在本轮内无限自循环或请求模型凭据。"
            )
            if plan.strategy == "baseline":
                prompt += (
                    "\n当前是单主队正确性基线阶段：读取最近失败的本队回执，只修一个具体问题。"
                    "先用失败 case_ids 做快速探针；探针通过才重跑完整15点和固定代表点。"
                    "避免重复通读未改动文件或反复委派同一分析；必要的独立源码审查仍保留。"
                    "本队完整验证和真实官测Pass之前，不扩增团队，不宣称SOTA。"
                )
            try:
                key = self.service.start_operation(name, "run", prompt)
            except ValueError:
                continue
            state.update(operation_id=key, turns=state["turns"] + 1, phase="optimizing")
            self.service.store.event(
                name, "swarm.turn.dispatched", operation_id=key, turn=state["turns"]
            )
        self.write(data)

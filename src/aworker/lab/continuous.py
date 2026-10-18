"""Independent, continuously replenished model work; never waits for official judging."""

import asyncio
import contextlib
import json
import time

from pydantic import BaseModel, Field


# ---- SwarmPlan --------------------------------------------------------------
class SwarmPlan(BaseModel):
    enabled: bool = False
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
        }

    async def configure(self, plan: SwarmPlan):
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
        for team in snapshot["teams"]:
            name = team["id"]
            if (
                not team["active"]
                or team["runtime"] != "deepagents"
                or team["model"] not in configured
            ):
                continue
            if plan.teams is not None and name not in plan.teams:
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
            try:
                key = self.service.start_operation(name, "run", prompt)
            except ValueError:
                continue
            state.update(operation_id=key, turns=state["turns"] + 1, phase="optimizing")
            self.service.store.event(
                name, "swarm.turn.dispatched", operation_id=key, turn=state["turns"]
            )
        self.write(data)

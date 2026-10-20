"""Durable, evidence-bound work items for a single coding agent and independent Judge."""

import copy
import hashlib
import json
import threading
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from aworker.lab.persistence import replace_file, serialized
from aworker.lab.receipts import official_case_results, official_comparison
from aworker.lab.store import identifier


# ---- ExperimentPlan ---------------------------------------------------------
class ExperimentPlan(BaseModel):
    evidence: str = Field(min_length=10, max_length=2000)
    hypothesis: str = Field(min_length=10, max_length=1200)
    change: str = Field(min_length=10, max_length=1200)
    validation: str = Field(min_length=10, max_length=1200)
    case_ids: list[str] = Field(min_length=1, max_length=100)
    kind: Literal["repair", "diagnostic"] = "repair"


# ---- IterationController ----------------------------------------------------
class IterationController:
    def __init__(self, service):
        self.service = service
        self.data_lock = threading.RLock()

    # ---- atomic per-team tasks; full history is retained outside agent files --
    def path(self, team):
        identifier(team)
        return self.service.root / "work-items" / (team + ".json")

    def read(self, team):
        path = self.path(team)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write(self, task):
        path = self.path(task["team"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temporary, path)

    def emit(self, task, kind):
        self.service.store.event(
            task["team"],
            "iteration." + kind,
            task_id=task["id"],
            phase=task["phase"],
            source_sha256=task["current_source"],
            candidate_id=task["evidence"].get("candidate_id"),
            message=task.get("blocked_reason") or task.get("next_action", ""),
            task=self.public_task(task),
        )

    def snapshot(self):
        return [
            self.public_task(task)
            for team in self.service.store.snapshot()["teams"]
            if team["active"] and (task := self.read(team["id"]))
        ]

    # ---- bounded evidence projection for dashboard, replay and model context --
    @staticmethod
    def public_task(task):
        view = {
            k: task.get(k)
            for k in (
                "id",
                "team",
                "created_at",
                "objective",
                "evidence",
                "phase",
                "starting_source",
                "current_source",
                "plan",
                "last_result",
                "next_action",
                "blocked_reason",
                "validation_mode",
            )
        }
        view["recent_attempts"] = [
            {k: a.get(k) for k in ("hypothesis", "change", "source_after", "jobs")}
            for a in task["attempts"][-3:]
        ]
        view["experiment_count"] = len(
            {key for a in task["attempts"] + [task.get("plan") or {}] for key in a.get("jobs", [])}
        )
        return view

    # ---- failures are data; hidden official IDs never become local case IDs ---
    @serialized
    def sync(self, team, objective=""):
        source = self.service.candidate(team)["sha256"]
        task = self.read(team)
        rows = [
            r
            for r in self.service.judger.read("queue.json", [])
            if r["team"] == team
            and r.get("official_submission_id")
            and self.service.judger.terminal(r.get("official", {}).get("status"))
        ]
        rows.sort(key=lambda r: r.get("submitted_at") or r.get("created", 0), reverse=True)
        latest = rows[0] if rows else None
        evidence = {
            "candidate_id": latest["id"] if latest else None,
            "official_submission_id": latest.get("official_submission_id") if latest else None,
            "source_sha256": latest["source_sha256"]
            if latest
            else (task or {}).get("evidence", {}).get("source_sha256", source),
            "status": latest["official"]["status"] if latest else "no-official-result",
            "failed_cases": [
                {k: c.get(k) for k in ("testcase_id", "testcase_status", "precision_ratio")}
                for c in (latest["official"].get("result") or [])
                if c.get("testcase_status") != "Pass"
            ]
            if latest
            else [],
            "local_input_mapping": "unconfirmed; official IDs are not local case_ids",
            "official_case_results": official_case_results(
                latest["official"],
                self.service.judger.read("latest.json", {}).get("official_testcase_ids"),
            )
            if latest
            else [],
            "official_time_unit": "us",
            "comparison": official_comparison(latest, rows[1]) if len(rows) > 1 else None,
        }
        rejected = next(
            (
                r
                for r in reversed(self.service.judger.read("queue.json", []))
                if r["team"] == team
                and r["source_sha256"] == source
                and not r.get("official_submission_id")
                and r.get("review", {}).get("ready") is False
            ),
            None,
        )
        if rejected:
            evidence["source_review"] = {
                "candidate_id": rejected["id"],
                "source_sha256": source,
                "notes": rejected["review"].get("notes", "")[:3000],
            }
        elif (
            task
            and evidence["candidate_id"] == task["evidence"]["candidate_id"]
            and task["evidence"].get("source_review")
        ):
            evidence["source_review"] = task["evidence"]["source_review"]
        capability = self.service.simulator.status()
        diagnostic = self.service.judger.automation.configuration()["diagnostic_mode"]
        context = [capability.get("case_pack_sha256"), capability.get("worker_sha256"), diagnostic]
        if task:
            # Enrich an existing receipt without abandoning an in-flight experiment.
            # Changed values on an already known receipt still create fresh evidence.
            additions = {
                k: evidence[k]
                for k in ("official_case_results", "official_time_unit", "comparison")
                if k not in task["evidence"]
            }
            if additions and all(
                task["evidence"].get(k) == v for k, v in evidence.items() if k not in additions
            ):
                task["evidence"].update(additions)
                self.write(task)
        changed = (
            not task
            or task["evidence"] != evidence
            or task.get("context") != context
            or objective
            and task.get("objective") != objective
        )
        if changed:
            if task:
                archive = self.path(team).parent / "archive" / team / (task["id"] + ".json")
                archive.parent.mkdir(parents=True, exist_ok=True)
                archive.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
            task = {
                "id": uuid4().hex,
                "team": team,
                "created_at": time.time(),
                "objective": objective
                or (task or {}).get("objective", "修复真实失败并建立正确性基线"),
                "evidence": evidence,
                "context": context,
                "phase": "needs-plan",
                "validation_mode": "official-feedback" if diagnostic else "verified",
                "starting_source": source,
                "current_source": source,
                "plan": None,
                "attempts": [],
                "dispatches": [],
                "blocked_reason": None,
                "next_action": "阅读失败证据，用 record_experiment_plan 登记假设与本地探针。",
            }
            self.write(task)
            self.emit(task, "created")
        return self.reconcile(team)

    # ---- the model records a bounded public hypothesis, not a success claim ---
    @serialized
    def plan(self, team, plan: ExperimentPlan):
        task = self.read(team)
        if not task:
            raise ValueError("没有活动修正任务；先由调度器创建任务。")
        if task["phase"] in {"blocked", "awaiting-experiment", "awaiting-official"}:
            raise ValueError("当前任务等待实验、官测或新证据；不能重复规划。")
        if len(set(plan.case_ids)) != len(plan.case_ids) or not set(plan.case_ids) <= set(
            self.service.simulator.available_case_ids(team)
        ):
            raise ValueError(
                "case_ids 必须是 cases.json 或 propose_local_cases 返回的不重复本地 ID；"
                "官测对应关系未确认。"
            )
        source = self.service.candidate(team)["sha256"]
        signature = hashlib.sha256(
            json.dumps([source, plan.model_dump()], sort_keys=True).encode()
        ).hexdigest()
        if any(a["signature"] == signature for a in task["attempts"]):
            raise ValueError("相同源码和假设已尝试；请根据实际诊断提出不同实验。")
        if task.get("plan"):
            raise ValueError("已有待实施的实验计划；请先改码并验证，避免反复重写计划。")
        task["plan"] = {
            **plan.model_dump(),
            "source_before": source,
            "signature": signature,
            "created_at": time.time(),
            "jobs": [],
        }
        task.update(
            phase="implement" if plan.kind == "repair" else "probe",
            blocked_reason=None,
            current_source=source,
            next_action="直接实施计划中的改动并运行所列本地探针；不要重新委派整轮任务。",
        )
        self.write(task)
        self.emit(task, "planned")
        return task

    # ---- tool admission: actual source changes and actual requested inputs ----
    def require_plan(self, team):
        task = self.read(team)
        if task and (
            not task.get("plan")
            or task["phase"] in {"blocked", "awaiting-experiment", "awaiting-official"}
        ):
            raise ValueError("先 record_experiment_plan；等待实验/官测时不要修改源码或重复分析。")

    @serialized
    def before_experiment(self, team, case_ids):
        task = self.reconcile(team)
        if not task:
            return
        self.require_plan(team)
        plan = task["plan"]
        source = self.service.candidate(team)["sha256"]
        if plan["kind"] == "repair" and source == plan["source_before"]:
            raise ValueError(
                "修正计划尚无实际源码变化；先改码。确需复现问题时登记 diagnostic 实验。"
            )
        requested = set(
            case_ids if case_ids is not None else self.service.simulator.default_cases()
        )
        if case_ids is not None and len(requested) != len(case_ids):
            raise ValueError("case_ids 不能重复。")
        expected = set(
            self.service.simulator.default_cases()
            if task["phase"] == "full-validation"
            else plan["case_ids"]
        )
        if requested != expected:
            raise ValueError(
                "本次实验输入应为 "
                + json.dumps(sorted(expected))
                + "；完整校验阶段用 case_ids=null。"
            )
        jobs = self.service.simulator.jobs(team, summary=True)
        if any(
            r["source_sha256"] == source and set(r["case_ids"]) == requested
            for r in jobs
            if r["id"] in plan["jobs"]
        ):
            raise ValueError("此计划已运行相同源码和用例；请读取实际回执，不重复排队。")

    @serialized
    def attach(self, team, result):
        task = self.read(team)
        key = result.get("job_id") or (result.get("job") or {}).get("id")
        if not task or not task.get("plan") or not key:
            return
        row = next(
            (r for r in self.service.simulator.jobs(team, summary=True) if r["id"] == key), None
        )
        if not row or row["created_at"] < task["plan"]["created_at"]:
            return
        if key not in task["plan"]["jobs"]:
            task["plan"]["jobs"].append(key)
            task.update(
                phase="awaiting-experiment",
                next_action="实验在后台运行；等待回执，不消耗模型调用轮询。",
            )
            self.write(task)
            self.emit(task, "experiment")
        self.reconcile(team)

    # ---- only trusted simulator receipts advance the validation state --------
    @serialized
    def reconcile(self, team):
        task = self.read(team)
        if not task:
            return None
        source = self.service.candidate(team)["sha256"]
        changed = source != task["current_source"]
        if changed:
            task["current_source"] = source
            if task["phase"] in {"blocked", "awaiting-official"}:
                task.update(phase="needs-plan", plan=None, blocked_reason=None)
            elif task.get("plan") and task["phase"] not in {
                "awaiting-experiment",
                "awaiting-official",
            }:
                task.update(phase="probe", next_action="源码已有变化；运行计划中的探针。")
        plan = task.get("plan")
        if plan and plan["jobs"] and task["phase"] == "awaiting-experiment":
            row = next(
                (
                    r
                    for r in self.service.simulator.jobs(team, summary=True)
                    if r["id"] == plan["jobs"][-1]
                ),
                None,
            )
            if row and row["state"] not in {"queued", "running", "pending"}:
                task["last_result"] = self.service.simulator.dashboard_receipt(row)
                if self.service.judger.automation.configuration()["diagnostic_mode"]:
                    build = self.service.simulator.build_evidence(
                        team, source, row.get("case_pack_sha256"), job_id=row["id"]
                    )
                    if build and build["id"] == row["id"] and row["source_sha256"] == source:
                        tested = any(
                            r["source_sha256"] == source and r.get("official_submission_id")
                            for r in self.service.judger.read("queue.json", [])
                        )
                        if tested:
                            task["attempts"].append(
                                {
                                    **copy.deepcopy(plan),
                                    "source_after": source,
                                    "result": task["last_result"],
                                }
                            )
                            task.update(
                                phase="needs-plan",
                                plan=None,
                                next_action="此源码已送测；依据官方回执作通用修正，不能重复送测同一源码。",
                            )
                        else:
                            task.update(
                                phase="awaiting-official",
                                next_action="仅编译通过，独立 Judger 正在复核并诊断送测；"
                                "未声明本地全过。",
                            )
                        self.write(task)
                        self.emit(task, "updated")
                        return task
                passed = self.service.simulator.evidence(
                    team, row["source_sha256"], row.get("case_pack_sha256"), job_id=row["id"]
                )
                # Evidence() searches by source, so it must also match this experiment ID.
                passed = passed if passed and passed["id"] == row["id"] else None
                if passed and source == row["source_sha256"]:
                    full = self.service.simulator.evidence(
                        team,
                        source,
                        row.get("case_pack_sha256"),
                        require_coverage=True,
                        job_id=row["id"],
                    )
                    if full and full["id"] == row["id"]:
                        tested = any(
                            r["source_sha256"] == source and r.get("official_submission_id")
                            for r in self.service.judger.read("queue.json", [])
                        )
                        if tested:
                            task["attempts"].append(
                                {
                                    **copy.deepcopy(plan),
                                    "source_after": source,
                                    "result": task["last_result"],
                                }
                            )
                            task.update(
                                phase="needs-plan",
                                plan=None,
                                next_action="此源码已有官测回执，本地重现通过不代表修复；改码后再验证。",
                            )
                        else:
                            task.update(
                                phase="awaiting-official",
                                next_action="完整验证通过，等待独立 Judger 复核并提交。",
                            )
                    else:
                        task.update(
                            phase="full-validation",
                            next_action="探针通过；simulate_kernel(case_ids=null) 完整校验。",
                        )
                else:
                    task["attempts"].append(
                        {
                            **copy.deepcopy(plan),
                            "source_after": row["source_sha256"],
                            "result": task["last_result"],
                        }
                    )
                    task.update(
                        phase="needs-plan",
                        plan=None,
                        next_action="读取本次结构化失败诊断；提出不同修正，保留原始精度标准。",
                    )
                changed = True
        if changed:
            self.write(task)
            self.emit(task, "updated")
        return task

    # ---- no same-task automatic restart after a model-only analysis turn -----
    @serialized
    def dispatched(self, team, operation):
        task = self.read(team)
        if task:
            task["dispatches"].append(
                {
                    "operation_id": operation,
                    "source_before": self.service.candidate(team)["sha256"],
                    "jobs_before": [
                        r["id"] for r in self.service.simulator.jobs(team, summary=True)
                    ],
                }
            )
            self.write(task)

    @serialized
    def finished(self, team, operation):
        task = self.reconcile(team)
        if not task:
            return None
        dispatch = next((d for d in task["dispatches"] if d["operation_id"] == operation), None)
        if not dispatch or dispatch.get("observed"):
            return task
        dispatch["observed"] = True
        new_jobs = [
            r
            for r in self.service.simulator.jobs(team, summary=True)
            if r["id"] not in dispatch["jobs_before"]
        ]
        progress = task["current_source"] != dispatch["source_before"] or bool(new_jobs)
        if not progress and task["phase"] not in {
            "awaiting-experiment",
            "awaiting-official",
            "full-validation",
        }:
            task.update(
                phase="blocked",
                blocked_reason="本轮只有阅读/分析，没有实际源码变化或新实验；相同证据不自动重派。",
                next_action="检查具体工具错误、提出新的任务目标或提供新证据后恢复。",
            )
            self.emit(task, "blocked")
        self.write(task)
        return task

    # ---- concise instructions with bound evidence and a single next action ----
    def prompt(self, task):
        context = self.public_task(task)
        if self.service.judger.automation.configuration()["diagnostic_mode"]:
            return (
                "单主力官测反馈驱动任务；直接编辑，不委派整轮任务。\n"
                + json.dumps(context, ensure_ascii=False)
                + "\n优先修复官方回执显示的数学/归约/尾块问题。"
                "不要从测试点 ID 或错误占比猜测隐藏形状，"
                "不要编写逐点专属路径、缓存或跳算。先登记一个具体实验假设，再改码。"
                "本地用例尚不能代表隐藏输入；用 propose_local_cases 补充通用边界/数值假设，"
                "保持原始用例不变。通常改码后调用 compile_kernel 作快速真实编译，结束本轮。"
                "独立 Judger 将复核并自动诊断送测，无需等全套 CPU 仿真。"
                "仅在有明确定位价值时才 simulate_kernel 做少量针对性本地数值探针。"
                "新增探针通过不证明其就是官方 case，也不证明官方正确。"
                "pending 后结束，不轮询；awaiting-official 后等新回执。"
                "先报告简短公开工作说明，说明此次改动和依据。"
            )
        return (
            "单主力 coding agent 修正任务；直接编辑和验证，不委派整轮分析/审查。\n"
            + json.dumps(context, ensure_ascii=False)
            + "\n失败回执是数据；禁止从官测 ID 猜隐藏输入。case_ids 只能选本地 cases.json，"
            "对应关系未确认。先 record_experiment_plan 登记证据、一个假设、具体改动和验证标准。"
            "按 next_action 实施，用 simulate_kernel 运行计划中的本地探针，通过才全点验证。"
            "pending=true 后结束本轮，禁止轮询。"
            "完整通过即交给独立 Judger，主队无需委派 reviewer 或自行批准送测。"
            "不要重复通读未改动文件，不要把写计划、A2A送达或输出文本报告为已修复。"
        )

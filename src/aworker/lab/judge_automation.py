"""Bounded official submissions and model feedback from the dashboard login session."""

import asyncio
import contextlib
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from aworker.lab.iteration import ExperimentPlan
from aworker.lab.judge_browser import (
    JudgeRejected,
    LoginRequired,
    SubmissionUncertain,
    TemplateChanged,
)
from aworker.lab.persistence import serialized
from aworker.lab.policy import inspect_source
from aworker.lab.project import project_manifest, source_display
from aworker.lab.selection import CandidateSelector


# ---- JudgeAutomation --------------------------------------------------------
class JudgeAutomation:
    def __init__(self, monitor):
        self.monitor = monitor
        self.service = monitor.service
        self.browser = monitor.browser
        self.selector = CandidateSelector(self)
        self.task = None
        self.wake = asyncio.Event()
        self.stopping = False
        self.busy = False
        self.phase = "stopped"
        self.message = "持续搜索与官测独立；仅精选 SOTA 挑战候选送测。"

    # ---- bounded configuration and lifecycle --------------------------------
    def configuration(self):
        raw = self.monitor.read("automation.json", {})
        return {
            "enabled": False,
            "max_submissions": 50,
            "selector_model": None,
            "diagnostic_mode": False,
            **{
                k: v
                for k, v in raw.items()
                if k not in {"max_rounds", "model_dispatches", "test_day"}
            },
        }

    def status(self):
        return {
            **{k: v for k, v in self.configuration().items() if k != "owner_hash"},
            "phase": self.phase,
            "message": self.message,
            "busy": self.busy,
            "budget": self.budget(),
            "selection": self.selector.status(),
        }

    async def configure(
        self, enabled, max_submissions=50, selector_model=None, diagnostic_mode=None
    ):
        if max_submissions is not None and not 1 <= max_submissions <= 100000:
            raise ValueError("设置有效的全局官测预算。")
        config = self.configuration()
        if enabled and not config.get("enabled"):
            config.update(run_id=uuid4().hex, started_at=time.time(), owner_hash=None)
        config.update(
            enabled=enabled,
            max_submissions=max_submissions,
            selector_model=selector_model,
        )
        if diagnostic_mode is not None:
            config["diagnostic_mode"] = diagnostic_mode
        self.monitor.write("automation.json", config)
        self.service.store.event(
            "controller",
            "judge.automation.configured",
            enabled=enabled,
            max_submissions=max_submissions,
            selector_model=selector_model,
            diagnostic_mode=config["diagnostic_mode"],
        )
        self.wake.set()
        if enabled:
            await self.start()
        else:
            self.phase = "stopping" if self.busy else "stopped"
            self.message = "正在收取本次提交响应。" if self.busy else "自动官测已暂停。"
        return self.status()

    def budget(self):
        config = self.configuration()
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        day = today
        used = sum(
            datetime.fromtimestamp(r["at"], timezone(timedelta(hours=8))).date().isoformat() == day
            for r in self.attempts()
        )
        return {
            "day": day,
            "timezone": "Asia/Shanghai",
            "used": used,
            "limit": config["max_submissions"],
            "remaining": max(0, config["max_submissions"] - used)
            if config["max_submissions"] is not None
            else None,
        }

    def budget_exhausted(self):
        remaining = self.budget()["remaining"]
        return remaining is not None and remaining <= 0

    def attempts(self):
        path = self.service.base_root / "judge-attempts.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def reserve_attempt(self, attempt):
        path = self.service.base_root / "judge-attempts.json"
        rows = self.attempts()
        rows.append(attempt)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    async def start(self):
        if self.configuration().get("enabled") and (not self.task or self.task.done()):
            self.stopping = False
            self.task = asyncio.create_task(self.loop())

    async def close(self):
        self.stopping = True
        self.wake.set()
        await self.selector.close()
        if self.task:
            await self.task
            self.task = None

    async def loop(self):
        while not self.stopping and self.configuration().get("enabled"):
            try:
                await self.tick()
            except Exception as exc:
                self.phase = "error"
                self.message = self.service.redact(str(exc))[:500]
                self.service.store.event(
                    "controller", "judge.automation.error", message=self.message
                )
            self.wake.clear()
            if self.stopping or not self.configuration().get("enabled"):
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), 20)

    # ---- source-bound readiness; no Host-only drafts or empty kernels --------
    def validation_evidence(self, row):
        if row.get("validation_mode") == "official-feedback":
            return self.service.simulator.build_evidence(
                row["team"],
                row["source_sha256"],
                row["case_pack_sha256"],
                job_id=row.get("simulation_job_id"),
            )
        return self.service.simulator.evidence(
            row["team"],
            row["source_sha256"],
            row["case_pack_sha256"],
            require_coverage=True,
            job_id=row.get("simulation_job_id"),
        )

    def readiness(self, row, require_review=True):
        if (
            row.get("validation_mode") == "official-feedback"
            and not self.configuration()["diagnostic_mode"]
        ):
            return False, "此候选仅供诊断；当前未开启官测驱动诊断模式。"
        if self.service.simulator.required or row.get("validation_mode") == "official-feedback":
            diagnostic = (
                self.configuration()["diagnostic_mode"]
                and row.get("validation_mode") == "official-feedback"
            )
            simulation = self.validation_evidence(row)
            if simulation is None or row.get("simulation_job_id") != simulation["id"]:
                return (
                    False,
                    "等待匹配源码的实际编译证据。"
                    if diagnostic
                    else "等待本队对该冻结源码和输入包完成通过的独立仿真。",
                )
        candidate = self.monitor.code(row["id"])
        manifest = project_manifest(self.service.root)
        required = manifest.get(
            "required_implementation_paths",
            [
                "op_host/confusion_mul_grad_infershape.cpp",
                "op_host/confusion_mul_grad_tiling.cpp",
                "op_kernel/confusion_mul_grad.h",
            ],
        )
        for name in required:
            text = candidate["files"].get(name, "")
            if not text or hashlib.sha256(text.encode()).hexdigest() == manifest[
                "project_files"
            ].get(name):
                return False, "尚未实现：" + name
            cleaned = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
            if re.search(
                r"\b(?:Init|Process|InferShape|TilingFunc)\s*\([^;{}]*\)\s*\{\s*\}", cleaned
            ):
                return False, "仍有空实现：" + name
        # Review the immutable package; the original team may already be coding its next version.
        report = inspect_source(
            source_display(candidate["files"], manifest.get("editable_paths")),
            manifest.get("entrypoint", "run_kernel"),
        )
        if not report.automated_pass:
            return False, "源码规则自查未通过。"
        review = row.get("review", {})
        if require_review and (
            not review.get("ready") or review.get("source_sha256") != row["source_sha256"]
        ):
            return False, "等待 reviewer 对同一源码版本作明确复核。"
        return True, "源码与复核匹配，等待官方编译和判题。"

    @serialized
    def update(self, key, **values):
        queue = self.monitor.read("queue.json", [])
        row = next(r for r in queue if r["id"] == key)
        row.update(values)
        self.monitor.write("queue.json", queue)
        return row

    @serialized
    def review(self, team, ready, notes, source_sha256=None):
        digest = self.service.candidate(team)["sha256"]
        if source_sha256 is not None and source_sha256 != digest:
            raise ValueError("源码在复核期间发生变化，请复核当前版本后重新记录。")
        queue = self.monitor.read("queue.json", [])
        row = next(
            (r for r in reversed(queue) if r["team"] == team and r["source_sha256"] == digest), None
        )
        if row is None:
            row = self.monitor.stage(team)
        review = {"ready": ready, "notes": notes[:8000], "source_sha256": digest, "at": time.time()}
        self.update(row["id"], review=review)
        self.service.store.event(team, "candidate.reviewed", candidate_id=row["id"], **review)
        self.wake.set()
        return review

    @serialized
    def review_frozen(self, key, digest, ready, notes):
        candidate = self.monitor.code(key)
        if candidate["source_sha256"] != digest or len(notes.strip()) < 10:
            raise ValueError("复核必须绑定读到的冻结源码并说明依据。")
        if ready:
            allowed, reason = self.readiness(candidate, require_review=False)
            if not allowed:
                raise ValueError(reason)
        review = {
            "ready": ready,
            "notes": notes[:8000],
            "source_sha256": digest,
            "at": time.time(),
            "reviewer": "independent-selector",
        }
        self.update(key, review=review)
        self.service.store.event(
            candidate["team"], "candidate.reviewed", candidate_id=key, **review
        )
        return review

    # ---- independent official lane, no all-team completion barrier -----------
    async def diagnose_current(self, team):
        if not self.configuration()["diagnostic_mode"]:
            raise ValueError("先开启官测驱动诊断模式。")
        if any(
            o["team"] == team and o["state"] == "running"
            for o in self.service.store.snapshot()["operations"]
        ):
            raise ValueError("主队正在改码；请等本轮结束或由主队调用 compile_kernel。")
        task = self.service.iterations.sync(team)
        if task["phase"] == "awaiting-official":
            return {"state": "awaiting-official", "message": task["next_action"]}
        if task["phase"] == "blocked":
            raise ValueError(task["blocked_reason"])
        if task.get("plan") is None:
            task = self.service.iterations.plan(
                team,
                ExperimentPlan(
                    evidence="User enabled official-feedback diagnosis; prior evidence: "
                    + json.dumps(
                        {
                            k: task["evidence"].get(k)
                            for k in (
                                "official_submission_id",
                                "source_sha256",
                                "status",
                                "failed_cases",
                            )
                        },
                        ensure_ascii=False,
                    )[:1600],
                    hypothesis="This general implementation needs official diagnosis; provisional "
                    "local cases do not identify hidden inputs.",
                    change="No edit: freeze and compile current source for independent review "
                    "and official diagnosis.",
                    validation="Compilation is not correctness. Read every official case result; "
                    "retain unknown hidden-input mappings.",
                    case_ids=self.service.simulator.default_cases()[:1],
                    kind="diagnostic",
                ),
            )
        selected = None if task["phase"] == "full-validation" else task["plan"]["case_ids"]
        self.service.iterations.before_experiment(team, selected)
        result = await self.service.simulator.evaluate(
            team,
            "judger-diagnostic-build",
            task["plan"]["hypothesis"],
            selected,
            evaluation_mode="compile-only",
        )
        self.service.iterations.attach(team, result)
        self.wake.set()
        return result

    async def tick(self):
        root = self.service.root
        config = self.configuration()
        if not config.get("enabled"):
            return
        queue = self.monitor.read("queue.json", [])
        if any(
            r.get("state") in {"submitting", "submission-uncertain", "blocked-template"}
            for r in queue
        ):
            self.phase, self.message = (
                "needs-reconciliation",
                "官测状态待确认；搜索继续，暂不发送新提交。",
            )
            return
        if config["diagnostic_mode"]:
            # Freeze current source as soon as an actual build exists, without a model-turn barrier.
            for team in self.service.store.snapshot()["teams"]:
                if not team["active"]:
                    continue
                try:
                    self.monitor.stage(
                        team["id"],
                        "Official-feedback diagnostic: compiled source; local numerical "
                        "coverage may be incomplete or failing. Not a verified SOTA.",
                    )
                except (ValueError, OSError):
                    continue
        # Comparing frozen source does not require a browser, NPU or idle teams.
        self.selector.schedule()
        if not self.browser.status()["opened"]:
            self.phase, self.message = (
                "awaiting-login",
                "请在面板连接官测。各队继续优化，无需等待登录。",
            )
            return
        session = await self.browser.call("check")
        if root != self.service.root:
            return
        if not session["connected"]:
            self.phase, self.message = "awaiting-login", session["message"]
            return
        config = self.configuration()
        principal = getattr(self.browser, "principal", None)
        if config.get("owner_hash") and principal and config["owner_hash"] != principal:
            await self.configure(
                False,
                config["max_submissions"],
                config.get("selector_model"),
            )
            self.phase, self.message = "account-changed", "登录账户已改变，请确认后重新开启官测。"
            return
        if principal and not config.get("owner_hash"):
            config["owner_hash"] = principal
            self.monitor.write("automation.json", config)
        async with self.monitor.lock:
            await self.monitor.refresh_tracked(
                self.monitor.read("latest.json", {}).get("rows", []), include_terminal=False
            )
        if root != self.service.root or not self.configuration().get("enabled") or self.stopping:
            return
        queue = self.monitor.read("queue.json", [])
        if any(
            r.get("official_submission_id")
            and not self.monitor.terminal(r.get("official", {}).get("status"))
            for r in queue
        ):
            self.phase, self.message = (
                "judging",
                "精选候选正在官测，团队并行优化；等待反馈后再选下一位挑战者。",
            )
            return
        if self.budget_exhausted():
            self.phase, self.message = (
                "budget-exhausted",
                "当日官测预算已用完，团队继续搜索、学习与积累候选。",
            )
            return
        self.selector.schedule()
        nomination = self.selector.nomination()
        if not nomination:
            if not self.selector.pool():
                self.phase, self.message = (
                    "awaiting-qualified-candidate",
                    "等待新源码编译完成及独立复核；诊断模式不要求本地全过。"
                    if config["diagnostic_mode"]
                    else "暂无满足门槛的未测候选：等待本队完整仿真通过及源码复核；"
                    "官测已连接，不占用额度。",
                )
            elif self.selector.status()["running"]:
                self.phase, self.message = (
                    "selecting",
                    "独立筛选器正在比较合格候选与已验证冠军。",
                )
            else:
                self.phase, self.message = (
                    "awaiting-nomination",
                    "合格候选尚未获独立提名；等待新候选或筛选器重试，团队继续优化。",
                )
            return
        if time.time() < self.configuration().get("next_submission_after", 0):
            self.phase, self.message = (
                "waiting-submit-slot",
                "已选出挑战候选，等待官测提交间隔；团队继续优化。",
            )
            return
        await self.submit(nomination["candidate_id"], automatic=True)

    # ---- a single serialized, non-retrying submit path -----------------------
    async def submit(self, key, automatic=False):
        if self.busy:
            raise ValueError("已有候选正在提交，请等待。")
        row = next((r for r in self.monitor.read("queue.json", []) if r["id"] == key), None)
        if row is None:
            raise ValueError("未找到冻结候选。")
        if row.get("official_submission_id") or row.get("state") in {
            "submitting",
            "submission-uncertain",
        }:
            raise ValueError("该候选已经提交或状态不确定，禁止重复提交。")
        if time.time() < self.configuration().get("next_submission_after", 0):
            raise ValueError("请等待官方提交间隔。")
        ready, reason = self.readiness(row)
        if not ready:
            raise ValueError(reason)
        nomination = self.selector.nomination()
        if automatic and (not nomination or nomination["candidate_id"] != key):
            raise ValueError("Judger 只提交独立筛选器提名的 SOTA 挑战候选。")
        if self.budget_exhausted():
            raise ValueError("全局每日官测预算已用完；团队仍可继续优化。")
        if any(
            r.get("official_submission_id")
            and not self.monitor.terminal(r.get("official", {}).get("status"))
            for r in self.monitor.read("queue.json", [])
        ):
            raise ValueError("先等待当前精选候选的官测回执。")
        root = self.service.root
        manifest = project_manifest(root)
        source = manifest["input_source"]
        candidate = self.monitor.code(key)
        self.busy = True
        self.phase, self.message = "submitting", row["team"] + " 正在提交官方评测。"
        attempted = False
        try:
            template = await self.browser.call("template", source["problem_id"])
            self.validate_template(template, manifest)
            if root != self.service.root:
                raise ValueError("提交前算子已切换。")
            if automatic and (self.stopping or not self.configuration().get("enabled")):
                self.phase, self.message = "stopped", "自动官测已暂停，本候选尚未发送。"
                return {"candidate_id": key, "state": "paused"}
            # Reserve the global attempt BEFORE POST. Ambiguous/rejected attempts count too.
            # Pausing/restarting must never reset a day's upper bound.
            if self.budget_exhausted():
                raise ValueError("每日官测预算已用完，暂不提交。")
            attempt = {
                "id": uuid4().hex,
                "at": time.time(),
                "candidate_id": key,
                "source_sha256": row["source_sha256"],
            }
            self.reserve_attempt(attempt)
            self.update(
                key,
                state="submitting",
                submit_attempt=attempt["id"],
                submitted_at=attempt["at"],
                submit_error="",
            )
            self.service.store.event(
                row["team"],
                "judge.submit.started",
                candidate_id=key,
                source_sha256=row["source_sha256"],
            )
            attempted = True
            files = [
                {"path": p, "content": candidate["files"][p]} for p in manifest["editable_paths"]
            ]
            submission_id = await self.browser.call(
                "submit", source["problem_id"], files, self.configuration().get("owner_hash")
            )
            self.update(
                key,
                official_submission_id=submission_id,
                binding="browser-session",
                state="tracking",
            )
            self.service.store.event(
                row["team"],
                "judge.submitted",
                candidate_id=key,
                submission_id=submission_id,
                source_sha256=row["source_sha256"],
                binding="browser-session",
            )
            return {"candidate_id": key, "submission_id": submission_id, "state": "tracking"}
        except LoginRequired as exc:
            self.update(key, state="awaiting-login", submit_error=str(exc))
            raise
        except SubmissionUncertain as exc:
            self.update(key, state="submission-uncertain", submit_error=str(exc))
            raise
        except JudgeRejected as exc:
            self.update(
                key,
                state="awaiting-submit-slot" if exc.retry_after else "submission-rejected",
                submit_error=str(exc),
            )
            if exc.retry_after:
                config = self.configuration()
                config["next_submission_after"] = time.time() + max(
                    exc.retry_after, self.service.settings.lab_judge_submit_interval
                )
                self.monitor.write("automation.json", config)
            raise
        except TemplateChanged as exc:
            self.update(key, state="blocked-template", submit_error=str(exc))
            raise
        except Exception as exc:
            self.update(
                key,
                state="submission-uncertain" if attempted else "awaiting-template",
                submit_error=self.service.redact(str(exc))[:500],
            )
            raise
        finally:
            config = self.configuration()
            config["next_submission_after"] = max(
                config.get("next_submission_after", 0),
                time.time() + self.service.settings.lab_judge_submit_interval,
            )
            self.monitor.write("automation.json", config)
            self.busy = False

    def validate_template(self, template, manifest):
        files = {
            r["path"]: r for r in template.get("files", []) if isinstance(r, dict) and "path" in r
        }
        if set(files) != set(manifest["project_files"]) or {
            p for p, r in files.items() if r.get("editable")
        } != set(manifest["editable_paths"]):
            raise TemplateChanged("官方工程或开放文件清单已改变，请重新导入后提交。")
        for name, row in files.items():
            baseline = (self.service.root / "challenge/project" / name).read_text(encoding="utf-8")
            if baseline.replace("\r\n", "\n") != str(row.get("content", "")).replace("\r\n", "\n"):
                raise TemplateChanged("官方工程模板已更新：" + name)

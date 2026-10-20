"""Read official public evidence and stage exact-source submission packages."""

import asyncio
import hashlib
import json
import math
import re
import threading
import time
import zipfile
from uuid import uuid4

import httpx

from aworker.lab.judge_automation import JudgeAutomation
from aworker.lab.judge_browser import JudgeBrowser
from aworker.lab.notices import NoticeOutbox
from aworker.lab.persistence import replace_file, serialized
from aworker.lab.project import project_manifest, source_identity
from aworker.lab.receipts import official_case_results
from aworker.lab.store import identifier


# ---- JudgeMonitor -----------------------------------------------------------
class JudgeMonitor:
    def __init__(self, service, client=None):
        self.service = service
        self.client = client
        self.task = None
        self.lock = asyncio.Lock()
        self.data_lock = threading.RLock()
        self.browser = JudgeBrowser(service.settings)
        self.automation = JudgeAutomation(self)
        self.notices = NoticeOutbox(self)

    # ---- restart recovery, only under the process service lock --------------
    @serialized
    def recover_submissions(self):
        queue = self.read("queue.json", [])
        if any(r.get("state") == "submitting" for r in queue):
            for row in queue:
                if row.get("state") == "submitting":
                    row.update(
                        state="submission-uncertain", submit_error="服务中断，禁止自动重发。"
                    )
            self.write("queue.json", queue)

    # ---- official public snapshots -----------------------------------------
    @property
    def folder(self):
        return self.service.root / "judge"

    def read(self, name: str, default):
        path = self.folder / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def write(self, name: str, data):
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        temp = path.with_suffix("." + uuid4().hex + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temp, path)

    def status(self) -> dict:
        snapshot = self.read("latest.json", {})
        return {
            "simulation_required": self.service.simulator.required,
            "simulation_default_cases": len(self.service.simulator.default_cases()),
            "watching": bool(self.task and not self.task.done()),
            "snapshot": snapshot,
            "queue": self.read("queue.json", []),
            "submission_transport": "project-browser-session",
            "automatic_submission": self.automation.configuration().get("enabled", False),
            "session": self.browser.status(),
            "automation": self.automation.status(),
            "champion": self.champion(),
            "profiler": "disabled" if self.service.execution_mode == "judge-only" else "optional",
            "simulation": self.service.simulator.status(),
        }

    # ---- bounded agent observations; full UI/history is still available separately ----
    def model_status(self, team, candidate_id=""):
        status = self.status()
        queue = sorted(status["queue"], key=lambda r: r.get("created", 0), reverse=True)
        own = [r for r in queue if r["team"] == team][:3]
        selected = [r for r in queue if r["id"] == candidate_id] if candidate_id else own
        if candidate_id and not selected:
            raise ValueError("unknown frozen candidate")
        detailed = {r["id"] for r in selected}
        visible = {r["id"]: r for r in [*queue[:12], *selected]}
        fields = (
            "id",
            "team",
            "source_sha256",
            "case_pack_sha256",
            "state",
            "official_submission_id",
            "simulation_job_id",
            "submit_error",
        )
        rows = []
        for row in visible.values():
            item = {k: row.get(k) for k in fields}
            official = row.get("official") or {}
            item["official"] = {k: official.get(k) for k in ("status", "score", "rank")}
            if row["id"] in detailed:
                item["official"]["result"] = official.get("result", [])
                item["official_case_results"] = official_case_results(
                    official, status["snapshot"].get("official_testcase_ids")
                )
                review = row.get("review") or {}
                item["review"] = {
                    "ready": review.get("ready"),
                    "notes": str(review.get("notes", ""))[:1500],
                }
            rows.append(item)
        snapshot = status["snapshot"]
        public = {
            k: snapshot.get(k)
            for k in (
                "problem_id",
                "problem_url",
                "official_testcase_ids",
                "input_status",
                "updated_at",
            )
        }
        public["rows"] = [
            {k: r.get(k) for k in ("rank", "score", "status", "submission_id")}
            for r in snapshot.get("rows", [])[:10]
        ]
        return {
            "snapshot": public,
            "queue": rows,
            "champion": status["champion"],
            "session": {k: status["session"].get(k) for k in ("opened", "connected", "state")},
            "automation": {k: status["automation"].get(k) for k in ("enabled", "phase", "budget")},
            "details": "Own latest 3 results include official cases. Use candidate_id "
            "to inspect another frozen result; read_judge_candidate reads source separately.",
        }

    async def sync(self) -> dict:
        async with self.lock:
            source = project_manifest(self.service.root).get("input_source", {})
            problem_id = source.get("problem_id", "")
            if not re.fullmatch(r"[0-9a-f]{24}", problem_id):
                raise ValueError("this operator has no official CANN Judge identity")
            root = self.service.root
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as owned:
                client = self.client or owned
                response, ranking = await asyncio.gather(
                    client.get("https://cannjudge.cn/api/problems/" + problem_id),
                    client.get("https://cannjudge.cn/api/problems/" + problem_id + "/ranking"),
                )
                response.raise_for_status()
                ranking.raise_for_status()
                problem, ranks = response.json(), ranking.json()
                if problem.get("code") == 0:
                    problem = problem["data"]
                if ranks.get("code") == 0:
                    ranks = ranks["data"]
            if root != self.service.root or problem.get("_id") != problem_id:
                raise ValueError("operator changed during judge synchronization")
            rows = [
                {
                    "rank": row.get("rank"),
                    "submission_id": row.get("submission_id"),
                    "submission_number": (row.get("submission") or {}).get("ID"),
                    "status": row.get("status"),
                    "score": row.get("score"),
                    "result": row.get("result", []),
                }
                for row in ranks.get("rows", [])
            ]
            snapshot = {
                "problem_id": problem_id,
                "title": problem.get("title"),
                "cann_version": problem.get("cann_version"),
                "problem_url": source["problem_url"],
                "statement_sha256": hashlib.sha256(problem.get("desc", "").encode()).hexdigest(),
                "official_testcase_ids": [
                    row["testcase_id"]["_id"] for row in problem.get("testcases", [])
                ],
                "total_ranked": ranks.get("total", len(rows)),
                "page": ranks.get("current", 1),
                "pages": ranks.get("pages", 1),
                "rows": rows,
                "input_status": "public specification known; hidden inputs unknown",
                "updated_at": time.time(),
            }
            old = self.read("latest.json", {})
            if {k: v for k, v in old.items() if k != "updated_at"} != {
                k: v for k, v in snapshot.items() if k != "updated_at"
            }:
                self.service.store.event(
                    "controller",
                    "judge.public.updated",
                    problem_id=problem_id,
                    total_ranked=snapshot["total_ranked"],
                    source="official-public",
                )
            self.write("latest.json", snapshot)
            await self.refresh_tracked(rows, include_terminal=False)
            return snapshot

    # ---- cancellable background monitoring ----------------------------------
    async def watch(self, enabled: bool):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        self.write("watch.json", {"enabled": enabled, "interval_seconds": 60})
        if enabled:
            self.task = asyncio.create_task(self.loop())
        return self.status()

    async def loop(self):
        delay = 60
        while self.read("watch.json", {}).get("enabled"):
            try:
                await self.sync()
                delay = 60
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.service.store.event(
                    "controller", "judge.sync.failed", message=self.service.redact(str(exc))[:1000]
                )
                delay = min(delay * 2, 600)
            await asyncio.sleep(delay)

    async def close(self):
        await self.automation.close()
        await self.notices.close()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        await self.browser.close()

    # ---- explicit known terminal statuses; unknown states never trigger work -
    @staticmethod
    def terminal(status):
        return re.sub(r"[^a-z]", "", str(status).lower()) in {
            "pass",
            "fail",
            "failed",
            "compileerror",
            "compilationerror",
            "ce",
            "runtimeerror",
            "re",
            "timelimitexceeded",
            "timeout",
            "tle",
            "wronganswer",
            "wa",
            "accuracyerror",
            "precisionerror",
            "memorylimitexceeded",
            "mle",
            "error",
            "invalid",
        }

    # ---- source-bound packages; no fabricated submit IDs --------------------
    @serialized
    def stage(self, team: str, proposal: str = "") -> dict:
        candidate = self.service.candidate(team)
        manifest = project_manifest(self.service.root)
        if not manifest.get("project_files"):
            raise ValueError("only an official multi-file project can be staged")
        diagnostic = self.automation.configuration()["diagnostic_mode"]
        simulation = (
            self.service.simulator.build_evidence(team, candidate["sha256"])
            if diagnostic
            else self.service.simulator.evidence(team, candidate["sha256"], require_coverage=True)
        )
        if (self.service.simulator.required or diagnostic) and simulation is None:
            raise ValueError(
                "当前源码尚无本队匹配的通过仿真记录，修正并 simulate_kernel 后再提名。"
            )
        policy = self.service.inspect_policy(team)
        if not policy.automated_pass:
            raise ValueError("candidate failed automated source checks")
        editable = manifest["editable_paths"]
        if not any(
            hashlib.sha256(candidate["files"][p].encode()).hexdigest()
            != manifest["project_files"][p]
            for p in editable
        ):
            raise ValueError("official empty project is unchanged; implement the operator first")
        case_hash = hashlib.sha256(
            (self.service.root / "challenge/cases.json").read_bytes()
        ).hexdigest()
        if diagnostic:
            case_hash = simulation["case_pack_sha256"]
        existing = next(
            (
                r
                for r in self.read("queue.json", [])
                if r["team"] == team
                and r["source_sha256"] == candidate["sha256"]
                and r["case_pack_sha256"] == case_hash
            ),
            None,
        )
        if existing:
            if simulation:
                existing = self.automation.update(
                    existing["id"],
                    simulation_job_id=simulation["id"],
                    validation_mode="official-feedback" if diagnostic else "verified",
                )
            if proposal.strip():
                self.automation.update(existing["id"], proposal=proposal[:6000])
            return existing
        key = uuid4().hex
        folder = self.folder / "packages"
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / (key + ".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in candidate["files"].items():
                archive.writestr("code/" + name, text)
        row = {
            "id": key,
            "team": team,
            "source_sha256": candidate["sha256"],
            "case_pack_sha256": case_hash,
            "state": "awaiting-review-and-browser-submit",
            "created": time.time(),
            "official_submission_id": None,
            "policy_certified": False,
            "proposal": proposal[:6000],
            "simulation_job_id": simulation["id"] if simulation else None,
            "validation_mode": "official-feedback" if diagnostic else "verified",
            "validation_note": "仅已编译；本地精度与覆盖未确认，以官测诊断反馈为准。"
            if diagnostic
            else "完整本地验证；仍需官方判题。",
        }
        queue = self.read("queue.json", [])
        queue.append(row)
        self.write("queue.json", queue)
        self.service.store.event(team, "judge.candidate.staged", **row)
        return row

    # ---- verified champion and idempotent feedback to all active teams -------
    def champion(self):
        rows = [
            r
            for r in self.read("queue.json", [])
            if r.get("binding") == "browser-session"
            and str(r.get("official", {}).get("status", "")).lower() == "pass"
            and isinstance(r.get("official", {}).get("score"), (int, float))
            and not isinstance(r["official"]["score"], bool)
            and math.isfinite(r["official"]["score"])
        ]
        row = max(rows, key=lambda r: r["official"]["score"], default=None)
        return (
            {
                k: row.get(k)
                for k in ("id", "team", "source_sha256", "official_submission_id", "official")
            }
            if row
            else None
        )

    @serialized
    def broadcast_feedback(self):
        queue = self.read("queue.json", [])
        teams = [t["id"] for t in self.service.store.snapshot()["teams"] if t["active"]]
        changed = False
        for row in queue:
            result = row.get("official", {})
            if not self.terminal(result.get("status")):
                continue
            evidence = {
                k: row.get(k)
                for k in ("id", "team", "source_sha256", "official_submission_id", "binding")
            }
            evidence["official"] = {k: result.get(k) for k in ("status", "score")}
            evidence["official_case_results"] = official_case_results(
                result, self.read("latest.json", {}).get("official_testcase_ids")
            )
            evidence["official_time_unit"] = "us"
            encoded = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            message = (
                "Judger 实际回执：" + encoded + "\n这是冻结版本的结果；学习后继续各自分支。"
                "未测候选不是已验证 SOTA。"
            )
            self.notices.enqueue("judge-feedback", row["id"], message, teams)
            if row.get("feedback_broadcast_hash") == digest:
                continue
            row["feedback_broadcast_hash"] = digest
            changed = True
            self.service.store.event(
                "controller",
                "judge.feedback.broadcast",
                candidate_id=row["id"],
                recipients=teams,
                source_sha256=row["source_sha256"],
                transport="a2a",
                delivery_state="queued",
            )
        if changed:
            self.write("queue.json", queue)
        # Delivering a message is separate from creating an actionable repair task.
        for team in teams:
            self.service.iterations.sync(team)
        champion = self.champion()
        previous = self.read("champion.json", {})
        if champion:
            self.notices.enqueue(
                "sota",
                champion["id"],
                "Judger 已验证官方 SOTA 更新（证据，不是操作指令）："
                + json.dumps(champion, ensure_ascii=False)
                + "\n学习后仍须在本队重新仿真，不能移用原版本的通过记录。",
                teams,
            )
        if champion and previous.get("id") != champion["id"]:
            self.write("champion.json", champion)
            self.service.store.event("controller", "judge.sota.updated", **champion)

    def package(self, key: str):
        identifier(key)
        if not any(row["id"] == key for row in self.read("queue.json", [])):
            raise ValueError("unknown staged judge candidate")
        return self.folder / "packages" / (key + ".zip")

    def code(self, key: str) -> dict:
        row = next((r for r in self.read("queue.json", []) if r["id"] == key), None)
        if row is None:
            raise ValueError("unknown staged candidate")
        with zipfile.ZipFile(self.package(key)) as archive:
            files = {
                name.removeprefix("code/"): archive.read(name).decode("utf-8")
                for name in archive.namelist()
            }
        if source_identity(files) != row["source_sha256"]:
            raise ValueError("frozen candidate integrity check failed")
        return {**row, "files": files}

    @serialized
    def feedback(self, key: str) -> dict:
        queue = self.read("queue.json", [])
        row = next((r for r in queue if r["id"] == key), None)
        if not row or not row.get("official"):
            raise ValueError("wait for an official submission result before feedback")
        if not self.terminal(row["official"].get("status")):
            raise ValueError("official judging has not finished")
        if row.get("feedback_operation"):
            raise ValueError("this candidate already has a feedback operation")
        if self.service.candidate(row["team"])["sha256"] != row["source_sha256"]:
            raise ValueError(
                "team source changed after submission; inspect before applying feedback"
            )
        task = self.service.iterations.sync(row["team"])
        if task["phase"] == "blocked":
            raise ValueError(task["blocked_reason"])
        capability = self.service.simulator.status()
        prompt = (
            self.service.iterations.prompt(task)
            + (
                "\n当前 CPU CANN 仿真器可用，使用 simulate_kernel 和结构化结果。"
                if capability["available"]
                else "\n当前仿真器不可用；如实报告等待环境，不声称已验证。"
            )
            + "\n实际 NPU 计时需单独设备环境；仿真结果不代表官测性能。"
        )
        key_op = self.service.start_operation(row["team"], "run", prompt)
        self.service.iterations.dispatched(row["team"], key_op)
        row["feedback_operation"] = key_op
        self.write("queue.json", queue)
        self.service.store.event(
            row["team"], "judge.feedback.started", candidate_id=key, operation_id=key_op
        )
        return {"team": row["team"], "operation_id": key_op}

    # ---- explicitly associated official submissions -------------------------
    @serialized
    def track(self, key: str, submission_id: str) -> dict:
        if not re.fullmatch(r"(?:[0-9a-f]{24}|[0-9]{1,12})", submission_id):
            raise ValueError("use the official submission number or object ID")
        queue = self.read("queue.json", [])
        row = next((r for r in queue if r["id"] == key), None)
        if row is None:
            raise ValueError("select a staged candidate before associating a submission")
        row.update(official_submission_id=submission_id, binding="user-reported", state="tracking")
        self.write("queue.json", queue)
        return row

    async def refresh_tracked(self, ranks: list[dict], include_terminal: bool = True):
        root = self.service.root
        queue = self.read("queue.json", [])
        updates = {}
        problem_id = project_manifest(self.service.root)["input_source"]["problem_id"]
        for row in queue:
            submission_id = row.get("official_submission_id")
            if not submission_id:
                continue
            match = next(
                (
                    r
                    for r in ranks
                    if submission_id
                    in {str(r.get("submission_id")), str(r.get("submission_number"))}
                ),
                None,
            )
            cached_terminal = not include_terminal and self.terminal(
                row.get("official", {}).get("status")
            )
            if cached_terminal:
                if match is None:
                    continue
                # Public rank can change; immutable, already received failure details need no poll.
                ranking = match
                match = {**row["official"], "rank": ranking.get("rank")}
                score = ranking.get("score")
                if (
                    str(match.get("status", "")).lower() == "pass"
                    and str(ranking.get("status", "")).lower() == "pass"
                    and isinstance(score, (int, float))
                    and not isinstance(score, bool)
                    and math.isfinite(score)
                ):
                    # The authenticated receipt may finish before the ranking assigns a score.
                    match["score"] = score
            elif match is None or (
                row.get("binding") == "browser-session" and self.browser.status()["connected"]
            ):
                try:
                    ranking = match
                    rank = match.get("rank") if match else None
                    if row.get("binding") == "browser-session":
                        submission = await self.browser.call("receipt", submission_id)
                    else:
                        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as owned:
                            response = await (self.client or owned).get(
                                "https://cannjudge.cn/api/submissions/" + submission_id
                            )
                            response.raise_for_status()
                            submission = response.json()
                    if submission.get("code") == 0:
                        submission = submission["data"]
                    associated = submission.get("problem_id") or submission.get("problem")
                    if isinstance(associated, dict):
                        associated = associated.get("_id")
                    if associated != problem_id:
                        raise ValueError("submission does not match this operator")
                    match = {k: submission.get(k) for k in ("status", "score", "result")}
                    match["rank"] = rank
                    if (
                        match.get("score") is None
                        and ranking
                        and str(match.get("status", "")).lower() == "pass"
                        and str(ranking.get("status", "")).lower() == "pass"
                        and isinstance(ranking.get("score"), (int, float))
                        and not isinstance(ranking["score"], bool)
                        and math.isfinite(ranking["score"])
                    ):
                        match["score"] = ranking["score"]
                except Exception as exc:
                    row["tracking_error"] = self.service.redact(str(exc))[:500]
                    updates[row["id"]] = row
                    continue
            if root != self.service.root:
                return
            result = {k: match.get(k) for k in ("status", "score", "rank", "result")}
            if isinstance(result["result"], list):
                result["result"] = [
                    {"testcase_status": "Hidden"} if r.get("testcase_status") == "Hidden" else r
                    for r in result["result"]
                    if isinstance(r, dict)
                ]
            row.pop("tracking_error", None)
            if row.get("official") != result:
                row["official"] = result
                row["state"] = "official-result" if self.terminal(result["status"]) else "tracking"
                self.service.store.event(
                    row["team"],
                    "judge.submission.updated",
                    candidate_id=row["id"],
                    submission_id=submission_id,
                    problem_id=problem_id,
                    source_sha256=row["source_sha256"],
                    binding=row.get("binding", "user-reported"),
                    official=result,
                    official_testcase_ids=self.read("latest.json", {}).get(
                        "official_testcase_ids", []
                    ),
                )
            updates[row["id"]] = row
        if updates and root == self.service.root:
            with self.data_lock:
                # A team can stage code, or a user can rebind a submission, during HTTP I/O.
                current = self.read("queue.json", [])
                for index, row in enumerate(current):
                    update = updates.get(row["id"])
                    if update and row.get("official_submission_id") == update.get(
                        "official_submission_id"
                    ):
                        for field in ("official", "state"):
                            if field in update:
                                current[index][field] = update[field]
                        if "tracking_error" in update:
                            current[index]["tracking_error"] = update["tracking_error"]
                        else:
                            current[index].pop("tracking_error", None)
                self.write("queue.json", current)
                self.broadcast_feedback()

"""The same engineering tools are available regardless of model vendor."""

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import tool

from aworker.lab.domain import Experience, Stage, StageUpdate
from aworker.lab.project import project_manifest

if TYPE_CHECKING:
    from aworker.lab.service import LabService


# ---- existing virtual workspace arguments become native relative paths ----
def workspace_arguments(workspace: Path, arguments: list[str]) -> list[str]:
    normalized = []
    root = workspace.resolve()
    for argument in arguments:
        parts = PurePosixPath(argument).parts
        if (
            len(parts) > 2
            and parts[0] == "/"
            and parts[1] in {"analysis", "project", "large_tool_results"}
        ):
            candidate = (root / argument.lstrip("/")).resolve()
            if not candidate.is_relative_to(root) or ".." in parts:
                raise ValueError("virtual script argument must stay inside the team workspace")
            if candidate.exists():
                argument = candidate.relative_to(root).as_posix()
        normalized.append(argument)
    return normalized


# ---- EngineeringTools -------------------------------------------------------
@dataclass
class EngineeringTools:
    service: "LabService"
    team: str
    run_id: str
    workspace: Path
    evaluations: int = 0
    budget_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---- tool construction --------------------------------------------------
    def build(self, read_only: bool = False, role: str | None = None):
        @tool
        def record_review(source_sha256: str, ready: bool, notes: str) -> str:
            """Reviewer-only source-bound decision to send code to official compilation.

            ready is not a correctness pass, compliance certificate, or performance result.
            Reject confirmed source/constraint blockers.
            Missing local hardware alone is not a blocker.
            source_sha256 must be the inspect_policy SHA of the version you actually reviewed.
            """
            if len(notes.strip()) < 10 or len(notes) > 8000:
                raise ValueError("review notes must contain 10–8000 characters")
            return json.dumps(
                self.service.judger.automation.review(self.team, ready, notes, source_sha256),
                ensure_ascii=False,
            )

        @tool
        def inspect_policy() -> str:
            """Check the current kernel against automated rules and the compliance checklist."""
            try:
                return self.service.inspect_policy(self.team, self.run_id).model_dump_json()
            except (ValueError, OSError) as exc:
                return json.dumps({"automated_pass": False, "error": str(exc)})

        @tool
        def list_public_results() -> str:
            """List shared evaluated artifacts, including source and input-pack identities."""
            self.service.simulator.require_learning(self.team)
            return json.dumps(self.service.public(include_source=False), ensure_ascii=False)

        @tool
        def read_public_code(artifact_id: str) -> str:
            """Read published source. Record its artifact identity when learning."""
            self.service.simulator.require_learning(self.team)
            return self.service.public_code(artifact_id)

        @tool
        def read_experiences() -> str:
            """Read evidence-linked experiences and unproven transfer hypotheses."""
            self.service.simulator.require_learning(self.team)
            return json.dumps(self.service.store.experiences(), ensure_ascii=False)

        @tool
        def read_team_messages() -> str:
            """Read messages other registered teams sent to this team."""
            self.service.simulator.require_learning(self.team)
            return json.dumps(self.service.store.messages(self.team), ensure_ascii=False)

        @tool
        async def send_team_message(recipient: str, message: str, artifact_id: str = "") -> str:
            """Send another registered team a concrete observation or public artifact reference."""
            self.service.team_folder(recipient)
            if not message.strip() or len(message) > 8000:
                raise ValueError("message must contain 1–8000 characters")
            return await self.service.send_message(
                self.team, recipient, message, artifact_id or None
            )

        @tool
        async def evaluate_kernel() -> str:
            """Freeze current kernel.asc and run the trusted full-input NPU evaluation queue."""
            async with self.budget_lock:
                if self.evaluations >= self.service.settings.lab_max_evaluations:
                    raise ValueError("this run's NPU evaluation budget is exhausted")
                self.evaluations += 1
            previous = {j["id"] for j in self.service.store.snapshot()["jobs"]}
            try:
                result = await self.service.evaluate(self.team, self.run_id)
                return json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                # Compilation is an ordinary engineering failure. Return evidence so the
                # model can repair its code and use the remaining evaluation budget.
                jobs = [
                    j
                    for j in self.service.store.snapshot()["jobs"]
                    if j["team"] == self.team and j["id"] not in previous
                ]
                result = {
                    "pass": False,
                    "execution_failed": True,
                    "error": self.service.redact(str(exc))[:3000],
                }
                self.service.store.stage(
                    self.team,
                    StageUpdate(
                        stage=Stage.EXECUTE,
                        state="failed",
                        message=result["error"],
                        run_id=self.run_id,
                    ),
                )
                if jobs:
                    result["job_id"] = jobs[-1]["id"]
                    log = self.service.root / "jobs" / jobs[-1]["id"] / "remote.log"
                    if log.is_file():
                        result["log_tail"] = log.read_text(encoding="utf-8", errors="replace")[
                            -8000:
                        ]
                return json.dumps(result, ensure_ascii=False)

        @tool
        def read_judge_status(candidate_id: str = "") -> str:
            """Read compact public status and the team's latest 3 official case results.

            Use candidate_id to select another frozen receipt. No log-parsing script is needed.
            """
            if not self.service.simulator.can_learn(self.team):
                return json.dumps(
                    {
                        "mode": "independent-first",
                        "simulation": self.service.simulator.status(),
                        "own_experiments": [
                            self.service.simulator.dashboard_receipt(r)
                            for r in self.service.simulator.jobs(self.team)[:8]
                        ],
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                self.service.judger.model_status(self.team, candidate_id), ensure_ascii=False
            )

        @tool
        def read_judge_candidate(candidate_id: str, file_path: str = "") -> str:
            """Read complete frozen editable source; pending code is not validated SOTA.

            Default includes all editable Host/Kernel files. Use an exact supporting_paths
            entry as file_path to read unchanged template/build files separately.
            """
            candidate = self.service.judger.code(candidate_id)
            if candidate["team"] != self.team:
                self.service.simulator.require_learning(self.team)
            files = candidate["files"]
            if file_path and file_path not in files:
                raise ValueError("choose an exact path listed in supporting_paths")
            editable = set(project_manifest(self.service.root)["editable_paths"])
            return json.dumps(
                {
                    **{
                        k: candidate.get(k)
                        for k in (
                            "id",
                            "team",
                            "source_sha256",
                            "case_pack_sha256",
                            "state",
                            "official",
                        )
                    },
                    "files": {
                        p: text
                        for p, text in files.items()
                        if p == file_path or not file_path and p in editable
                    },
                    "supporting_paths": sorted(set(files) - editable),
                },
                ensure_ascii=False,
            )

        @tool
        async def simulate_kernel(
            hypothesis: str = "",
            case_ids: list[str] | None = None,
            learned_from: list[str] | None = None,
        ) -> str:
            """Freeze this team's exact source and independently compile/run CANN 910B4 simulation.

            Defaults to ALL trusted local INPUT cases (15 for this operator), not hidden cases.
            Runs functional PVModel checks first, then detailed CAModel profiling on fixed
            representative cases. Functional wall time is never NPU time or an official score.
            If pending=true, end this model turn immediately with a brief queued status.
            Do not poll or edit frozen work while awaiting the job; the scheduler resumes you.
            An explicit case_ids subset is a probe and cannot satisfy the full submission gate.
            Returns a structured result or pending job. Use read_simulation_results with
            section=log/profile for paged compiler diagnostics or profiling previews.
            Correct and retry failed/slower changes. Never inherit another team's measured pass.
            """
            result = await self.service.simulator.evaluate(
                self.team, self.run_id, hypothesis, case_ids, learned_from
            )
            if isinstance(result.get("job"), dict):
                result = {
                    "job": self.service.simulator.model_summary(result["job"]),
                    "details": "Use read_simulation_results(job_id, section=log/profile) "
                    "for paged diagnostics; no file parsing script is needed.",
                }
            return json.dumps(result, ensure_ascii=False)

        @tool
        def read_simulation_results(
            job_id: str = "",
            team: str = "",
            section: Literal["summary", "log", "profile"] = "summary",
            case_id: str = "",
            offset: int = 0,
            limit: int = 8000,
        ) -> str:
            """Read structured experiment results directly, without file parsing scripts.

            Defaults to a compact correctness/profile summary, including when job_id is given.
            For details request section=log, or section=profile with a listed case_id.
            Detailed text is paged by offset/limit (max 12000 characters); follow next_offset.
            Peer learning requires an own completed simulation. Never infer official scores.
            """
            target = team or self.team
            if target != self.team:
                self.service.simulator.require_learning(self.team)
            if not job_id and (section != "summary" or case_id or offset):
                raise ValueError("provide job_id before requesting detailed sections or offsets")
            result = (
                self.service.simulator.model_result(job_id, target, section, case_id, offset, limit)
                if job_id
                else {
                    "capability": self.service.simulator.status(),
                    "jobs": [
                        self.service.simulator.dashboard_receipt(row)
                        for row in self.service.simulator.jobs(target)[:8]
                    ],
                    "details": "Use job_id for a structured summary; section=log/profile "
                    "returns paged diagnostics. No file parsing is needed.",
                }
            )
            return json.dumps(result, ensure_ascii=False)

        @tool
        def queue_official_test(proposal: str = "") -> str:
            """Freeze the exact multi-file candidate into a reviewable CANN Judge ZIP.

            Judger submits it after source-bound review when official login and automation
            are enabled AND the independent selector nominates it as the best challenger.
            proposal explains the concrete change, evidence, and unknowns versus public SOTA.
            Other teams keep working; not every frozen candidate will be tested.
            """
            try:
                return json.dumps(self.service.judger.stage(self.team, proposal))
            except ValueError as exc:
                return json.dumps({"staged": False, "error": str(exc)})

        @tool
        def read_evaluation_log(job_id: str, start_line: int = 0, max_lines: int = 160) -> str:
            """Read this team's trusted compiler/device log to diagnose and repair a failed job."""
            owned = any(
                j["id"] == job_id and j["team"] == self.team
                for j in self.service.store.snapshot()["jobs"]
            )
            if not owned or start_line < 0 or not 1 <= max_lines <= 400:
                return json.dumps({"error": "select an owned job and valid log range"})
            folder = self.service.root / "jobs" / job_id
            path = folder / "remote.log"
            if not path.is_file():
                path = folder / "transport.log"
            if not path.is_file():
                return json.dumps({"job_id": job_id, "error": "log is not available yet"})
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return json.dumps(
                {
                    "job_id": job_id,
                    "start_line": start_line,
                    "total_lines": len(lines),
                    "text": "\n".join(lines[start_line : start_line + max_lines]),
                },
                ensure_ascii=False,
            )

        @tool
        def publish_result() -> str:
            """Publish only after this exact source and input pack passed a real job."""
            try:
                return json.dumps(self.service.publish(self.team, self.run_id), ensure_ascii=False)
            except ValueError as exc:
                self.service.store.stage(
                    self.team,
                    StageUpdate(
                        stage=Stage.SHARE, state="failed", message=str(exc), run_id=self.run_id
                    ),
                )
                return json.dumps({"published": False, "error": str(exc)})

        @tool
        def record_experience(
            title: str,
            conditions: str,
            action: str,
            limitations: str,
            evidence_job: str,
            transfer_hypothesis: bool = False,
        ) -> str:
            """Distill a reusable observation, bound to a real passed NPU job and its limits."""
            item = Experience(
                title=title,
                conditions=conditions,
                action=action,
                limitations=limitations,
                evidence_job=evidence_job,
                scope="transfer-hypothesis" if transfer_hypothesis else self.service.operator,
            )
            try:
                return self.service.record_experience(self.team, self.run_id, item)
            except ValueError as exc:
                self.service.store.stage(
                    self.team,
                    StageUpdate(
                        stage=Stage.DISTILL, state="failed", message=str(exc), run_id=self.run_id
                    ),
                )
                return json.dumps({"recorded": False, "error": str(exc)})

        @tool
        async def run_python(script_path: str, arguments: list[str] | None = None) -> str:
            """Run a workspace Python analysis script; use evaluate_kernel for NPU access.

            Use evaluate_kernel for NPU compilation and measurement. This local developer tool is
            for trusted team code; it is not a hardened multi-tenant operating-system sandbox.
            CWD is the team workspace. Existing /analysis/, /project/ and /large_tool_results/
            arguments are mapped to workspace-relative paths on Windows, macOS and Linux.
            Scripts should use relative paths for any literal filenames they open.
            """
            script = (self.workspace / script_path.lstrip("/")).resolve()
            if not script.is_relative_to(self.workspace.resolve()) or script.suffix != ".py":
                raise ValueError("script must be a .py file inside the team workspace")
            if not script.is_file():
                raise ValueError("write the analysis script into the workspace first")
            args = arguments or []
            if len(args) > 32 or any(len(a) > 4096 for a in args):
                raise ValueError("too many or too long script arguments")
            args = workspace_arguments(self.workspace, args)
            # Keep credentials, model endpoint configuration and inherited Python hooks out.
            environment = self.service.settings.analysis_environment()
            completed = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-I", str(script), *args],
                cwd=self.workspace,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            return json.dumps(
                {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout[-16000:],
                    "stderr": completed.stderr[-8000:],
                },
                ensure_ascii=False,
            )

        common = [
            read_simulation_results,
            inspect_policy,
            list_public_results,
            read_public_code,
            read_experiences,
            read_team_messages,
            send_team_message,
            read_evaluation_log,
            read_judge_status,
            read_judge_candidate,
        ]
        if role == "reviewer":
            common.append(record_review)
        return (
            common
            if read_only
            else common
            + [
                run_python,
                simulate_kernel,
                queue_official_test,
                evaluate_kernel,
                publish_result,
                record_experience,
            ]
        )

"""Controller and real graph protocol fixtures. No paid calls or real accuracy claims."""

import asyncio
import hashlib
import json
import time

import pytest
from langchain_core.messages import AIMessage
from test_judge_automation import lab as lab
from test_simulation import fixture_receipt, worker_heartbeat
from test_unified_lab import ScriptedModel
from test_unified_lab import service as service

from aworker.lab.iteration import ExperimentPlan, IterationController
from aworker.lab.prepare import refresh_team_guidance
from aworker.lab.tools import EngineeringTools


# ---- immutable official and local protocol fixtures -------------------------
def official(service, submission="a" * 24):
    row = {
        "id": submission + "-fixture",
        "team": "gpt-001",
        "created": time.time(),
        "submitted_at": time.time(),
        "source_sha256": service.candidate("gpt-001")["sha256"],
        "official_submission_id": submission,
        "official": {
            "status": "Wrong Answer",
            "result": [
                {
                    "testcase_id": "hidden-id-unmapped",
                    "testcase_status": "Wrong Answer",
                    "precision_ratio": 0.99,
                }
            ],
        },
    }
    queue = service.judger.read("queue.json", [])
    service.judger.write("queue.json", queue + [row])
    return row


# ---- one declared probe; no manual success flag -----------------------------
def plan(service, **updates):
    data = dict(
        evidence="Explicit test failure receipt, not a measured kernel result",
        hypothesis="Test hypothesis: revise a general reduction method",
        change="Change the test fixture source to exercise identity binding",
        validation="Original thresholds and actual local simulator receipt required",
        case_ids=service.simulator.default_cases()[:1],
    )
    return ExperimentPlan(**(data | updates))


# ---- change a fixture request, never production or hidden input --------------
def receipt(service, selected, state="completed"):
    row = fixture_receipt(service, state=state)
    folder = service.simulator.spool / "jobs" / row["id"]
    path = folder / "request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    request["case_ids"] = selected
    path.write_text(json.dumps(request), encoding="utf-8")
    row.update(case_ids=selected, request_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    row["cases"] = [c for c in row["cases"] if c["id"] in selected]
    (folder / "result.json").write_text(json.dumps(row), encoding="utf-8")
    return row


# ---- authoritative feedback, stable task and new-evidence recovery ----------
def test_official_failure_creates_one_bound_task_and_archives_on_new_receipt(lab):
    row = official(lab)
    task = lab.iterations.sync("gpt-001")
    assert task["evidence"]["official_submission_id"] == row["official_submission_id"]
    assert task["evidence"]["failed_cases"][0]["testcase_id"] == "hidden-id-unmapped"
    assert "unconfirmed" in task["evidence"]["local_input_mapping"]
    assert lab.iterations.sync("gpt-001")["id"] == task["id"]
    assert IterationController(lab).read("gpt-001")["id"] == task["id"]
    official(lab, "b" * 24)
    following = lab.iterations.sync("gpt-001")
    assert following["id"] != task["id"]
    assert (lab.root / "work-items/archive/gpt-001" / (task["id"] + ".json")).is_file()


# ---- the plan cannot silently replace IDs or count analysis as a repair ------
def test_repair_requires_valid_local_probe_and_actual_code_change(lab):
    lab.iterations.sync("gpt-001")
    with pytest.raises(ValueError, match="case_ids"):
        lab.iterations.plan("gpt-001", plan(lab, case_ids=["hidden-id-unmapped"]))
    task = lab.iterations.plan("gpt-001", plan(lab))
    with pytest.raises(ValueError, match="源码变化"):
        lab.iterations.before_experiment("gpt-001", task["plan"]["case_ids"])
    source = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n// explicit fixture change", encoding="utf-8"
    )
    assert lab.iterations.sync("gpt-001")["id"] == task["id"]
    lab.iterations.before_experiment("gpt-001", task["plan"]["case_ids"])
    with pytest.raises(ValueError, match="本次实验输入"):
        lab.iterations.before_experiment("gpt-001", None)


# ---- real receipt integrity and probe -> complete validation -> Judge --------
def test_probe_then_full_validation_uses_trusted_receipts_and_ignores_old_proofs(lab):
    fixture_receipt(lab)  # Deliberate pre-task full proof must not complete a fresh repair.
    lab.iterations.sync("gpt-001")
    task = lab.iterations.plan("gpt-001", plan(lab, kind="diagnostic"))
    probe = receipt(lab, task["plan"]["case_ids"])
    lab.iterations.attach("gpt-001", {"job": probe})
    assert lab.iterations.read("gpt-001")["phase"] == "full-validation"
    lab.iterations.before_experiment("gpt-001", None)
    full = receipt(lab, lab.simulator.default_cases())
    lab.iterations.attach("gpt-001", {"job": full})
    result = lab.iterations.read("gpt-001")
    assert result["phase"] == "awaiting-official"
    assert result["evidence"]["status"] == "no-official-result"
    assert lab.iterations.snapshot()[0]["experiment_count"] == 2
    assert "dispatches" not in lab.iterations.snapshot()[0]


# ---- edited code and stale adapter evidence cannot inherit a probe's pass ---
def test_stale_worker_proof_does_not_advance_or_manufacture_success(lab):
    lab.iterations.sync("gpt-001")
    task = lab.iterations.plan("gpt-001", plan(lab, kind="diagnostic"))
    row = receipt(lab, task["plan"]["case_ids"])
    folder = lab.simulator.spool / "jobs" / row["id"]
    row["worker_sha256"] = "wrong-worker"
    (folder / "result.json").write_text(json.dumps(row), encoding="utf-8")
    lab.iterations.attach("gpt-001", {"job": row})
    assert lab.iterations.read("gpt-001")["phase"] == "needs-plan"
    with pytest.raises(ValueError, match="已尝试"):
        lab.iterations.plan("gpt-001", plan(lab, kind="diagnostic"))


# ---- reproducing a locally passing official failure is not a new candidate ---
def test_unchanged_wrong_answer_source_is_not_left_waiting_for_duplicate_submission(lab):
    official(lab)
    lab.iterations.sync("gpt-001")
    lab.iterations.plan(
        "gpt-001", plan(lab, kind="diagnostic", case_ids=lab.simulator.default_cases())
    )
    full = receipt(lab, lab.simulator.default_cases())
    lab.iterations.attach("gpt-001", {"job": full})
    task = lab.iterations.read("gpt-001")
    assert task["phase"] == "needs-plan" and task["plan"] is None
    assert "不代表修复" in task["next_action"]


# ---- independent review blockers also become actionable evidence ------------
def test_source_bound_review_rejection_returns_work_to_coder(lab):
    task = lab.iterations.sync("gpt-001")
    lab.judger.write(
        "queue.json",
        [
            {
                "id": "fixture-review",
                "team": "gpt-001",
                "source_sha256": task["current_source"],
                "review": {"ready": False, "notes": "Explicit fixture tiling defect"},
            }
        ],
    )
    updated = lab.iterations.sync("gpt-001")
    assert updated["id"] != task["id"]
    assert updated["evidence"]["source_review"]["notes"] == "Explicit fixture tiling defect"


# ---- same objective + same evidence never automatically repeats paid work ---
def test_no_progress_blocks_redispatch_even_after_explicit_same_plan_resume(lab, monkeypatch):
    calls = []

    def dispatch(*args):
        calls.append(args)
        lab.store.operation("fixture-operation", "gpt-001", "run")
        return "fixture-operation"

    monkeypatch.setattr(lab, "start_operation", dispatch)
    lab.swarm.write({"enabled": True, "main_team": "gpt-001", "prompt": "fixture objective"})
    lab.swarm.tick()
    lab.store.operation_finished("fixture-operation", "completed")
    lab.iterations.finished("gpt-001", "fixture-operation")
    assert lab.iterations.read("gpt-001")["phase"] == "blocked"
    data = lab.swarm.read()
    data["progress"]["gpt-001"].update(observed="fixture-operation", next_at=0)
    lab.swarm.write(data)
    lab.swarm.tick()
    assert len(calls) == 1
    task = lab.iterations.sync("gpt-001", "a different focused repair objective")
    assert task["phase"] == "needs-plan"


# ---- real graph: recoverable admission errors, one model and actual file edit --
def test_single_coder_graph_records_plan_then_edits_without_subagent_calls(service, monkeypatch):
    service.swarm.write({"enabled": True, "strategy": "baseline", "main_team": "team-a"})
    service.iterations.sync("team-a")
    path = service.team_folder("team-a") / "kernel.asc"
    original = path.read_text(encoding="utf-8")
    edit = {
        "file_path": "/kernel.asc",
        "old_string": original.splitlines()[0],
        "new_string": original.splitlines()[0] + "\n// planned fixture edit\n",
    }
    data = plan(service).model_dump()
    model = ScriptedModel(
        responses=[
            AIMessage("", tool_calls=[{"id": "unplanned", "name": "edit_file", "args": edit}]),
            AIMessage(
                "", tool_calls=[{"id": "plan", "name": "record_experiment_plan", "args": data}]
            ),
            AIMessage("", tool_calls=[{"id": "edit", "name": "edit_file", "args": edit}]),
            AIMessage("Explicit fixture plan and edit; not a measured correctness claim."),
        ]
    )
    built, offered = [], []

    def build(key):
        built.append(key)
        return model

    def bind(self, tools, **kwargs):
        offered.extend(t.name for t in tools)
        return self

    monkeypatch.setattr(service.registry, "build", build)
    monkeypatch.setattr(ScriptedModel, "bind_tools", bind)
    asyncio.run(service.run_team("team-a", "Fixture direct coding task"))
    assert len(built) == 1 and "task" not in offered
    assert path.read_text(encoding="utf-8").count("planned fixture edit") == 1
    assert any(e["kind"] == "iteration.tool.blocked" for e in service.store.events())
    assert service.iterations.read("team-a")["phase"] == "probe"


# ---- feedback prompts follow real environment capability and latest receipt --
def test_feedback_uses_available_simulator_and_registered_task(lab, monkeypatch):
    worker_heartbeat(lab)
    row = official(lab)
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture-op")
    lab.judger.feedback(row["id"])
    assert "No local server, simulator" not in calls[0][2]
    assert "simulate_kernel" in calls[0][2]
    assert "hidden-id-unmapped" in calls[0][2]
    assert lab.iterations.read("gpt-001")["dispatches"][0]["operation_id"] == "fixture-op"


# ---- peer learning gate never hides the team's own official failure ----------
def test_own_official_feedback_is_visible_before_first_passing_simulation(lab):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    row = official(lab)
    tool = next(
        t
        for t in EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001")).build()
        if t.name == "read_judge_status"
    )
    output = json.loads(tool.invoke({}))
    assert output["mode"] == "independent-first"
    assert output["own_official"][0]["id"] == row["id"]
    assert output["own_official"][0]["official"]["result"][0]["precision_ratio"] == 0.99
    with pytest.raises(ValueError, match="先完成"):
        tool.invoke({"candidate_id": "another-team-candidate"})


# ---- upgrade generated instructions, preserve code, cases and user skills ----
def test_existing_workspace_guidance_refresh_is_narrow_and_recoverable(lab):
    folder = lab.team_folder("gpt-001")
    source = lab.candidate("gpt-001")["sha256"]
    cases = (folder / "cases.json").read_bytes()
    (folder / "TEAM.md").write_text("legacy generated instructions", encoding="utf-8")
    custom = folder / "skills/custom/SKILL.md"
    custom.parent.mkdir()
    custom.write_text("user skill fixture", encoding="utf-8")
    refresh_team_guidance(lab.root, "gpt-001")
    assert "single-coder" in (folder / "TEAM.md").read_text(encoding="utf-8")
    assert "record_experiment_plan" in (folder / "skills/kernel-engineering/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert custom.read_text(encoding="utf-8") == "user skill fixture"
    assert lab.candidate("gpt-001")["sha256"] == source
    assert (folder / "cases.json").read_bytes() == cases
    assert list((lab.root / "guidance-history/gpt-001").glob("*/TEAM.md"))

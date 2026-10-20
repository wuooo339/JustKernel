"""Diagnostic submission/probe contracts; all browser/compiler results here are fixtures."""

import asyncio
import hashlib
import json
import time

import pytest
from test_judge_automation import FakeBrowser
from test_judge_automation import lab as lab
from test_simulation import fixture_receipt, worker_heartbeat

from aworker.lab.iteration import ExperimentPlan
from aworker.lab.probes import LocalCaseProposal, local_cases, propose_cases
from aworker.lab.receipts import official_comparison
from aworker.lab.tools import EngineeringTools


# ---- immutable compile-only fixture, deliberately no numerical pass ----------
def build_fixture(lab):
    worker_heartbeat(lab)
    row = fixture_receipt(lab)
    folder = lab.simulator.spool / "jobs" / row["id"]
    request = folder / "request.json"
    data = json.loads(request.read_text(encoding="utf-8"))
    data["evaluation_mode"] = "compile-only"
    request.write_text(json.dumps(data), encoding="utf-8")
    row.update(
        request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
        state="completed",
        phase="compiled",
        evaluation_mode="compile-only",
        compile_pass=True,
        functional_pass=False,
        cases=[],
        compiled_binaries=[],  # CANN package layouts need not expose standalone .o files.
    )
    (folder / "result.json").write_text(json.dumps(row), encoding="utf-8")
    return row


# ---- real-feedback-shaped fixture, no hidden tensor values -------------------
def official_fixture(lab):
    row = {
        "id": "receipt-fixture",
        "team": "gpt-001",
        "source_sha256": lab.candidate("gpt-001")["sha256"],
        "official_submission_id": "b" * 24,
        "created": time.time(),
        "submitted_at": time.time(),
        "official": {
            "status": "Wrong Answer",
            "result": [
                {
                    "testcase_id": "hidden-id",
                    "testcase_status": "Wrong Answer",
                    "precision_ratio": 0.999,
                }
            ],
        },
    }
    lab.judger.write("queue.json", [row])
    return row


# ---- strict mode remains strict; diagnostic opt-in keeps compile/source binding ----
def test_diagnostic_build_is_not_a_pass_and_requires_opt_in(lab):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    proof = build_fixture(lab)
    source = proof["source_sha256"]
    assert lab.simulator.evidence("gpt-001", source, require_coverage=True) is None
    assert lab.simulator.build_evidence("gpt-001", source)["id"] == proof["id"]
    with pytest.raises(ValueError, match="仿真"):
        lab.judger.stage("gpt-001")
    asyncio.run(lab.judger.automation.configure(False, None, "gpt-api", diagnostic_mode=True))
    row = lab.judger.stage("gpt-001")
    assert row["validation_mode"] == "official-feedback"
    assert row["simulation_job_id"] == proof["id"]
    assert lab.judger.automation.readiness(row, require_review=False)[0]
    assert not lab.judger.automation.readiness(row)[0]
    asyncio.run(lab.judger.automation.configure(False, None, "gpt-api", diagnostic_mode=False))
    assert not lab.judger.automation.readiness(row, require_review=False)[0]
    assert lab.judger.champion() is None


# ---- a tampered request/build or another source never qualifies --------------
def test_build_binding_rejects_request_and_source_drift(lab):
    row = build_fixture(lab)
    assert lab.simulator.build_evidence("gpt-001", "different-source") is None
    path = lab.simulator.spool / "jobs" / row["id"] / "request.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert lab.simulator.build_evidence("gpt-001", row["source_sha256"]) is None


# ---- an approved diagnostic cannot disappear behind a permanent deferral ----
def test_submitted_current_source_waits_for_final_receipt_before_new_repair(lab):
    previous = official_fixture(lab)
    source = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    source.write_text(source.read_text() + "// fixture new version\n", encoding="utf-8")
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    task = lab.iterations.sync("gpt-001")
    assert task["phase"] == "needs-plan"
    proof = build_fixture(lab)
    current = lab.judger.stage("gpt-001")
    auto.update(current["id"], official_submission_id="c" * 24, official={"status": "Running"})
    task = lab.iterations.reconcile("gpt-001")
    assert task["phase"] == "awaiting-official"
    assert task["evidence"]["official_submission_id"] == previous["official_submission_id"]
    with pytest.raises(ValueError, match="等待"):
        lab.iterations.require_plan("gpt-001")
    assert lab.simulator.build_evidence("gpt-001", proof["source_sha256"])
    auto.update(current["id"], official={"status": "Wrong Answer", "result": []})
    task = lab.iterations.sync("gpt-001")
    assert task["phase"] == "needs-plan"
    assert task["evidence"]["official_submission_id"] == "c" * 24


def test_frozen_candidate_keeps_its_exact_build_when_a_later_probe_exists(lab):
    first = build_fixture(lab)
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    row = lab.judger.stage("gpt-001")
    auto.review_frozen(row["id"], row["source_sha256"], True, "Fixture immutable build review.")
    row = lab.judger.read("queue.json", [])[0]
    later = build_fixture(lab)
    assert later["id"] != first["id"]
    assert auto.validation_evidence(row)["id"] == first["id"]
    assert auto.readiness(row)[0]
    request = lab.simulator.spool / "jobs" / first["id"] / "request.json"
    request.write_text(request.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert not auto.readiness(row)[0]  # A newer valid build cannot repair tampered evidence.


def test_iteration_reconciles_its_attached_build_not_a_newer_same_source_probe(lab):
    official_fixture(lab)
    source = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    source.write_text(source.read_text() + "// fixture repair\n", encoding="utf-8")
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    lab.iterations.sync("gpt-001")
    lab.iterations.plan(
        "gpt-001",
        ExperimentPlan(
            evidence="Fixture official precision feedback; no real execution.",
            hypothesis="Fixture build/probe receipt identity remains stable.",
            change="No source edit; diagnostic protocol only.",
            validation="Bind the attached build even if another experiment is newer.",
            case_ids=lab.simulator.default_cases(),
            kind="diagnostic",
        ),
    )
    first = build_fixture(lab)
    later = build_fixture(lab)
    lab.iterations.attach("gpt-001", {"job_id": first["id"]})
    task = lab.iterations.read("gpt-001")
    assert task["phase"] == "awaiting-official"
    assert task["plan"]["jobs"] == [first["id"]]
    assert task["last_result"]["id"] != later["id"]


def test_deferred_reviewed_baseline_resumes_without_another_model_call(lab):
    build_fixture(lab)
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    row = lab.judger.stage("gpt-001")
    auto.review_frozen(
        row["id"],
        row["source_sha256"],
        True,
        "Fixture independent source review; compilation is not correctness.",
    )
    selector = auto.selector
    lab.judger.write(
        "selection.json",
        {
            "phase": "deferred",
            "fingerprint": selector.fingerprint(),
            "nomination": None,
            "next_at": time.time() + 3600,
        },
    )
    selector.schedule()
    assert selector.nomination()["candidate_id"] == row["id"]
    assert selector.task is None
    assert not lab.judger.read("queue.json", [])[0].get("official_submission_id")
    assert lab.judger.champion() is None


@pytest.mark.parametrize("change", ["unreviewed", "rejected", "different-source", "tampered-build"])
def test_deferred_baseline_rechecks_source_review_and_compile_binding(lab, change):
    proof = build_fixture(lab)
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    row = lab.judger.stage("gpt-001")
    if change != "unreviewed":
        auto.review_frozen(
            row["id"],
            row["source_sha256"],
            change != "rejected",
            "Fixture review for testing source-bound admission, not a real kernel.",
        )
    if change == "different-source":
        source = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
        source.write_text(source.read_text() + "// changed fixture\n", encoding="utf-8")
    if change == "tampered-build":
        path = lab.simulator.spool / "jobs" / proof["id"] / "request.json"
        path.write_text(path.read_text() + " ", encoding="utf-8")
    selector = auto.selector
    lab.judger.write(
        "selection.json",
        {
            "phase": "deferred",
            "fingerprint": selector.fingerprint(),
            "nomination": None,
        },
    )
    selector.schedule()
    assert selector.nomination() is None
    assert selector.task is None


# ---- obsolete histories and compile-only receipts do not trigger N² deep scans --
def test_peer_learning_skips_old_workers_and_build_only_receipts(lab, monkeypatch):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    build_fixture(lab)
    old = fixture_receipt(lab)
    old["worker_sha256"] = "obsolete-worker"
    path = lab.simulator.spool / "jobs" / old["id"] / "result.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    examined = []
    monkeypatch.setattr(lab.simulator, "evidence", lambda *a, **k: examined.append(a))
    assert not lab.simulator.can_learn("gpt-001")
    assert examined == []


# ---- unchanged feedback falsifies a gain; it does not identify a hidden shape --
def test_official_comparison_keeps_unknown_input_mapping(lab):
    before = official_fixture(lab)
    after = {
        **before,
        "id": "new-receipt",
        "official_submission_id": "c" * 24,
        "source_sha256": "d" * 64,
        "submitted_at": before["submitted_at"] + 10,
    }
    compared = official_comparison(after, before)
    assert compared["accuracy_changes"][0]["same_accuracy_feedback"] is True
    lab.judger.write("queue.json", [before, after])
    work = lab.iterations.sync("gpt-001")
    assert work["evidence"]["comparison"] == compared
    assert "shape" not in compared["accuracy_changes"][0]
    assert (
        official_comparison(
            {**after, "official": {"status": "Compile Error", "result": None}}, before
        )["accuracy_changes"]
        == []
    )


# ---- independent Judge can stage/submit before the main model turn finishes ---
def test_auto_diagnostic_submission_does_not_wait_for_model_turn_or_local_pass(lab):
    proof = build_fixture(lab)
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    lab.judger.write("automation.json", {**auto.configuration(), "enabled": True})
    browser = FakeBrowser(lab)
    lab.judger.browser = auto.browser = browser
    auto.selector.schedule = lambda: None
    lab.store.operation("still-coding", "gpt-001", "run")
    asyncio.run(auto.tick())
    row = lab.judger.read("queue.json", [])[0]
    assert row["source_sha256"] == proof["source_sha256"]
    assert row["validation_mode"] == "official-feedback"
    assert not any(method == "submit" for method, _ in browser.calls)
    auto.review_frozen(
        row["id"],
        row["source_sha256"],
        True,
        "Fixture source plausibility review only; numeric validation explicitly unproven.",
    )
    auto.selector.nominate(
        row["id"],
        row["source_sha256"],
        "Fixture informative general repair; diagnostic measurement only, no pass claimed.",
    )
    asyncio.run(auto.tick())
    submitted = lab.judger.read("queue.json", [])[0]
    assert submitted["official_submission_id"] == "a" * 24
    assert submitted["state"] == "tracking"
    assert len([x for x in browser.calls if x[0] == "submit"]) == 1
    with pytest.raises(ValueError, match="重复"):
        asyncio.run(auto.submit(row["id"]))
    assert lab.judger.champion() is None


# ---- no local cap still records attempts and respects server retry state -----
def test_unlimited_local_budget_preserves_attempt_history(lab):
    auto = lab.judger.automation
    for i in range(51):
        auto.reserve_attempt({"id": str(i), "at": time.time()})
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))
    assert auto.budget()["used"] == 51
    assert auto.budget()["remaining"] is None
    assert auto.budget()["limit"] is None
    assert not auto.budget_exhausted()
    asyncio.run(auto.configure(False, 50, "gpt-api"))
    assert auto.budget_exhausted()
    assert auto.configuration()["diagnostic_mode"] is True


# ---- compile completion hands off without manufacturing functional coverage ---
def test_controller_hands_off_compile_only_receipt(lab):
    asyncio.run(lab.judger.automation.configure(False, None, "gpt-api", diagnostic_mode=True))
    task = lab.iterations.sync("gpt-001")
    lab.iterations.plan(
        "gpt-001",
        ExperimentPlan(
            evidence="Fixture official uncertainty",
            hypothesis="Fixture diagnose unchanged source using an actual compile",
            change="No source edit; fixture build only",
            validation="Compiler receipt only; no numeric claim",
            case_ids=lab.simulator.default_cases(),
            kind="diagnostic",
        ),
    )
    proof = build_fixture(lab)
    task = lab.iterations.read("gpt-001")
    task["plan"]["jobs"] = [proof["id"]]
    task["phase"] = "awaiting-experiment"
    lab.iterations.write(task)
    done = lab.iterations.reconcile("gpt-001")
    assert done["phase"] == "awaiting-official"
    assert done["last_result"]["functional_pass"] is False
    assert done["validation_mode"] == "official-feedback"
    assert "compile_kernel" in lab.iterations.prompt(done)


# ---- hypotheses add coverage without replacing or 'discovering' hidden INPUT ---
def test_feedback_probes_are_separate_reproducible_and_constrained(lab):
    baseline = (lab.root / "challenge/cases.json").read_bytes()
    receipt = official_fixture(lab)
    proposal = {"shape": [7, 129], "dtype": "float32", "axis": [-1], "keep_dims": True, "seed": 77}
    rows = propose_cases(
        lab,
        "gpt-001",
        receipt["official_submission_id"],
        "Fixture hypothesis: odd row tails may expose an alignment defect",
        [proposal],
    )
    assert rows[0]["official_case_id"] is None
    assert rows[0]["axis"] == [1]
    assert rows[0]["provenance"] == "feedback-hypothesis-unconfirmed"
    assert len(local_cases(lab, "gpt-001")) == 1
    propose_cases(
        lab,
        "gpt-001",
        receipt["official_submission_id"],
        "Same reproducible fixture hypothesis",
        [proposal],
    )
    assert len(local_cases(lab, "gpt-001")) == 1
    assert (lab.root / "challenge/cases.json").read_bytes() == baseline
    text, selected = lab.simulator.case_pack("gpt-001", [rows[0]["id"]])
    assert json.loads(text)[0]["id"] == rows[0]["id"]
    assert selected == [rows[0]["id"]]
    assert lab.simulator.case_pack("gpt-001")[0].encode() == baseline
    assert len(lab.simulator.default_cases()) == 15
    lab.iterations.sync("gpt-001")
    plan = ExperimentPlan(
        evidence="Fixture feedback",
        hypothesis="Fixture test odd row tails",
        change="No edit, probe only",
        validation="Fixed original reference/tolerance",
        case_ids=selected,
        kind="diagnostic",
    )
    assert lab.iterations.plan("gpt-001", plan)["plan"]["case_ids"] == selected
    with pytest.raises(ValueError, match="actual terminal"):
        propose_cases(lab, "gpt-001", "guessed-id", "Fixture unconfirmed hypothesis", [proposal])
    for changes in [
        {"shape": [0, 3]},
        {"shape": [9999999, 99999]},
        {"dtype": "float64"},
        {"axis": [7]},
        {"low": -11},
        {"official_case_id": "hidden"},
        {"tolerance": 100},
    ]:
        with pytest.raises(ValueError):
            LocalCaseProposal.model_validate(proposal | changes)


# ---- real tool dispatch serializes compile-only requests; no fake execution ---
def test_compile_tool_enqueues_build_only_and_keeps_numeric_tool_available(lab):
    worker_heartbeat(lab)
    lab.settings = lab.settings.model_copy(update={"lab_simulation_wait_seconds": 0.01})
    asyncio.run(lab.judger.automation.configure(False, None, "gpt-api", diagnostic_mode=True))
    tools = {
        t.name: t
        for t in EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001")).build()
    }

    async def exercise():
        try:
            result = json.loads(
                await tools["compile_kernel"].ainvoke({"hypothesis": "Fixture compile diagnostic"})
            )
            path = lab.simulator.spool / "jobs" / result["job_id"] / "request.json"
            request = json.loads(path.read_text(encoding="utf-8"))
            assert request["evaluation_mode"] == "compile-only"
            assert request["profile_case_ids"] == []
            assert result["pending"]
            assert lab.simulator.evidence("gpt-001", request["source_sha256"]) is None
            assert "simulate_kernel" in tools
        finally:
            await lab.simulator.close()

    asyncio.run(exercise())


# ---- large full receipts do not overflow the bounded experiment-plan field ---
def test_diagnose_current_with_complete_feedback_enqueues_a_real_request(lab):
    row = official_fixture(lab)
    row["official"]["result"] = [
        {
            "testcase_id": str(i),
            "testcase_status": "Wrong Answer",
            "precision_ratio": 0.999,
            "time": 10000 + i,
            "best_time": 1234 + i,
        }
        for i in range(15)
    ]
    lab.judger.write("queue.json", [row])
    worker_heartbeat(lab)
    lab.settings = lab.settings.model_copy(update={"lab_simulation_wait_seconds": 0.01})
    auto = lab.judger.automation
    asyncio.run(auto.configure(False, None, "gpt-api", diagnostic_mode=True))

    async def exercise():
        try:
            result = await auto.diagnose_current("gpt-001")
            assert result["pending"]
            task = lab.iterations.read("gpt-001")
            assert len(task["evidence"]["official_case_results"]) == 15
            assert len(task["plan"]["evidence"]) < 2000
            request = json.loads(
                (lab.simulator.spool / "jobs" / result["job_id"] / "request.json").read_text(
                    encoding="utf-8"
                )
            )
            assert request["evaluation_mode"] == "compile-only"
        finally:
            await lab.simulator.close()

    asyncio.run(exercise())


# ---- optional probes run with their own frozen pack and the unchanged adapter ---
def test_proposed_probe_can_be_sent_to_the_actual_worker_protocol(lab):
    row = official_fixture(lab)
    probe = propose_cases(
        lab,
        "gpt-001",
        row["official_submission_id"],
        "Fixture odd-tail numeric hypothesis",
        [{"shape": [5, 127], "dtype": "float32", "axis": [1]}],
    )[0]
    baseline = (lab.root / "challenge/cases.json").read_bytes()
    worker_heartbeat(lab)
    lab.settings = lab.settings.model_copy(update={"lab_simulation_wait_seconds": 0.01})

    async def exercise():
        try:
            result = await lab.simulator.evaluate(
                "gpt-001", "fixture", "Fixture numeric probe", [probe["id"]]
            )
            request = json.loads(
                (lab.simulator.spool / "jobs" / result["job_id"] / "request.json").read_text(
                    encoding="utf-8"
                )
            )
            assert request["evaluation_mode"] == "functional-then-profile"
            assert json.loads(request["cases_json"])[0]["official_case_id"] is None
            assert request["case_pack_sha256"] != hashlib.sha256(baseline).hexdigest()
            assert request["profile_case_ids"] == []
            assert (lab.root / "challenge/cases.json").read_bytes() == baseline
        finally:
            await lab.simulator.close()

    asyncio.run(exercise())

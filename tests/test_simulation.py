"""Local protocol fixtures only. These tests never claim real simulation or official scores."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from test_judge_automation import lab as lab

from aworker.lab.simulation import SimulationRequest
from aworker.lab.tools import EngineeringTools


# ---- protocol fixtures ------------------------------------------------------
def worker_heartbeat(service):
    service.simulator.spool.mkdir(parents=True, exist_ok=True)
    (service.simulator.spool / "heartbeat.json").write_text(
        json.dumps(
            {
                "schema": "justkernel.simulator.worker.v1",
                "state": "ready",
                "worker_sha256": service.simulator.identity(),
                "target_soc": "Ascend910B4",
                "at": time.time(),
            }
        ),
        encoding="utf-8",
    )


# ---- fixture_receipt --------------------------------------------------------
def fixture_receipt(service, team="gpt-001", state="completed"):
    source = service.candidate(team)
    cases = (service.root / "challenge/cases.json").read_bytes().decode()
    key = uuid4().hex
    request = SimulationRequest(
        id=key,
        workspace_id=service.simulator.workspace_id,
        team=team,
        operator=service.operator,
        files=source["files"],
        source_sha256=source["sha256"],
        cases_json=cases,
        case_pack_sha256=hashlib.sha256(cases.encode()).hexdigest(),
        case_ids=service.simulator.default_cases(),
        worker_sha256=service.simulator.identity(),
        hypothesis="Explicit local protocol fixture; no execution claim",
        created_at=time.time(),
    )
    folder = service.simulator.spool / "jobs" / key
    folder.mkdir(parents=True)
    path = folder / "request.json"
    path.write_text(request.model_dump_json(by_alias=True), encoding="utf-8")
    result = {
        **request.model_dump(by_alias=True, exclude={"files", "cases_json"}),
        "schema": "justkernel.simulation.v1",
        "source": "cann-simulator",
        "state": state,
        "functional_pass": state == "completed",
        "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "cases": [
            {
                "id": name,
                "pass": True,
                "profiling_files": [{"path": "explicit-fixture-not-real.csv"}],
            }
            for name in request.case_ids
        ],
    }
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return result


# ---- independent ownership and source/input integrity -----------------------
def test_simulation_index_is_bounded_without_large_profiler_previews(lab, monkeypatch):
    record = fixture_receipt(lab)
    record["cases"][0]["profiling_files"] = [{"preview": "large-explicit-fixture" * 5000}]
    monkeypatch.setattr(lab.simulator, "jobs", lambda team=None: [record] * 30)
    reader = next(
        t
        for t in EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001")).build()
        if t.name == "read_simulation_results"
    )
    output = json.loads(reader.invoke({}))
    assert len(output["jobs"]) == 8
    assert output["jobs"][0]["cases"][0]["pass"]
    assert "large-explicit-fixture" not in json.dumps(output)
    assert "job_id" in output["details"]


def test_expanding_input_range_invalidates_an_otherwise_complete_cached_proof(lab):
    path = lab.root / "challenge/cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    for case in cases:
        case["distribution"].update(low=-1.0, high=1.0)
    path.write_text(json.dumps(cases), encoding="utf-8")
    record = fixture_receipt(lab)
    assert lab.simulator.evidence(record["team"], record["source_sha256"], require_coverage=True)
    for case in cases:
        case["distribution"].update(low=-10.0, high=10.0)
    path.write_text(json.dumps(cases), encoding="utf-8")
    assert (
        lab.simulator.evidence(record["team"], record["source_sha256"], require_coverage=True)
        is None
    )


def test_job_listing_caches_decoding_but_never_returns_mutable_cache_entries(lab, monkeypatch):
    record = fixture_receipt(lab)
    folder = lab.simulator.spool / "jobs" / record["id"]
    reads = []
    original = Path.read_text

    def counted(path, *args, **kwargs):
        if path.parent == folder:
            reads.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    first = lab.simulator.jobs(record["team"])
    first[0]["cases"][0]["pass"] = False
    second = lab.simulator.jobs(record["team"])
    assert second[0]["cases"][0]["pass"] is True
    assert reads.count("request.json") == reads.count("result.json") == 1
    cached = lab.simulator._request_cache[folder / "request.json"][1]
    assert "files" not in cached and "cases_json" not in cached


def test_job_cache_refreshes_worker_receipt_changes(lab):
    record = fixture_receipt(lab)
    assert lab.simulator.evidence(record["team"], record["source_sha256"])
    path = lab.simulator.spool / "jobs" / record["id"] / "result.json"
    previous = path.stat()
    record.update(state="failed", functional_pass=False)
    path.write_text(json.dumps(record), encoding="utf-8")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000))
    assert lab.simulator.jobs(record["team"])[0]["state"] == "failed"
    assert lab.simulator.evidence(record["team"], record["source_sha256"]) is None


def test_cached_request_metadata_cannot_bypass_original_byte_integrity(lab):
    record = fixture_receipt(lab)
    assert lab.simulator.evidence(record["team"], record["source_sha256"])
    path = lab.simulator.spool / "jobs" / record["id"] / "request.json"
    previous = path.stat()
    raw = path.read_bytes()
    changed = raw.replace(b"fixture", b"FIXTURE")
    assert changed != raw and len(changed) == len(raw)
    path.write_bytes(changed)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert lab.simulator.evidence(record["team"], record["source_sha256"]) is None


def test_default_is_all_fifteen_and_an_authentic_subset_is_only_a_probe(lab):
    cases = json.loads((lab.root / "challenge/cases.json").read_text(encoding="utf-8"))
    assert len(lab.simulator.default_cases()) == len(cases) == 15
    assert not any(c.get("official_case_id") for c in cases)
    record = fixture_receipt(lab)
    folder = lab.simulator.spool / "jobs" / record["id"]
    path = folder / "request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    request["case_ids"] = request["case_ids"][:9]
    path.write_text(json.dumps(request), encoding="utf-8")
    record.update(
        case_ids=request["case_ids"],
        cases=record["cases"][:9],
        request_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    (folder / "result.json").write_text(json.dumps(record), encoding="utf-8")
    assert lab.simulator.evidence(record["team"], record["source_sha256"])
    assert (
        lab.simulator.evidence(record["team"], record["source_sha256"], require_coverage=True)
        is None
    )


def test_simulation_receipt_cannot_transfer_between_teams_or_changed_sources(lab):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    lab.auto_teams(1, "gpt-api")
    first = fixture_receipt(lab)
    assert lab.simulator.evidence("gpt-001", first["source_sha256"])
    assert lab.simulator.evidence("gpt-002", first["source_sha256"]) is None
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_text(path.read_text() + "// distinct fixture version\n", encoding="utf-8")
    assert lab.simulator.evidence("gpt-001", lab.candidate("gpt-001")["sha256"]) is None


# ---- record and immutable request must agree --------------------------------
@pytest.mark.parametrize("mutation", ["source", "inputs", "request", "coverage", "worker"])
def test_misbound_or_stale_simulation_cannot_qualify(lab, mutation):
    record = fixture_receipt(lab)
    digest = record["source_sha256"]
    if mutation == "source":
        digest = "a" * 64
        record["source_sha256"] = digest
    elif mutation == "inputs":
        record["case_pack_sha256"] = "a" * 64
    elif mutation == "request":
        record["request_sha256"] = "a" * 64
    elif mutation == "coverage":
        record["cases"][0]["id"] = "draft-02"
    else:
        record["worker_sha256"] = "a" * 64
    path = lab.simulator.spool / "jobs" / record["id"] / "result.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert lab.simulator.evidence("gpt-001", digest) is None


# ---- simulation is required before sharing/official candidacy ---------------
def test_peer_learning_is_held_until_an_own_successful_simulation(lab):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    tools = {
        t.name: t
        for t in EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001")).build()
    }
    fixture_receipt(lab, state="failed")
    with pytest.raises(ValueError, match="先完成"):
        tools["read_team_messages"].invoke({})
    assert json.loads(tools["read_judge_status"].invoke({}))["mode"] == "independent-first"
    fixture_receipt(lab)
    assert isinstance(json.loads(tools["read_team_messages"].invoke({})), list)


# ---- old source-only candidates do not bypass the new gate -------------------
def test_official_candidate_requires_this_teams_exact_passing_simulation(lab):
    staged = lab.judger.stage("gpt-001")
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    with pytest.raises(ValueError, match="仿真"):
        lab.judger.stage("gpt-001")
    assert not lab.judger.automation.readiness(staged, require_review=False)[0]
    proof = fixture_receipt(lab)
    updated = lab.judger.stage("gpt-001")
    assert updated["simulation_job_id"] == proof["id"]
    assert lab.judger.automation.readiness(updated, require_review=False)[0]


# ---- offline CPU worker never falls back to source-only model dispatch -------
def test_continuous_search_waits_for_simulator_and_resumes_independently(lab, monkeypatch):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture-op")
    lab.swarm.write({"enabled": True})
    lab.swarm.tick()
    assert not calls and lab.swarm.status()["waiting_for"] == "simulator"
    worker_heartbeat(lab)
    lab.swarm.tick()
    assert len(calls) == 1 and "simulate_kernel" in calls[0][2]
    assert lab.swarm.status()["waiting_for"] is None


# ---- Windows/WSL clock skew and pending experiment adoption ------------------
def test_small_worker_clock_skew_does_not_interrupt_an_experiment(lab):
    worker_heartbeat(lab)
    path = lab.simulator.spool / "heartbeat.json"
    worker = json.loads(path.read_text())
    worker["at"] = time.time() + 1
    path.write_text(json.dumps(worker), encoding="utf-8")
    assert lab.simulator.status()["available"]


# ---- subscription retries never enqueue a duplicate physical experiment -----
def test_retry_waits_for_same_pending_own_source_instead_of_enqueuing_again(lab, monkeypatch):
    worker_heartbeat(lab)
    record = fixture_receipt(lab, state="queued")
    folder = lab.simulator.spool / "jobs" / record["id"]

    async def finish_fixture(_):
        record.update(state="completed", functional_pass=True)
        (folder / "result.json").write_text(json.dumps(record), encoding="utf-8")

    monkeypatch.setattr("aworker.lab.simulation.asyncio.sleep", finish_fixture)
    result = asyncio.run(lab.simulator.evaluate("gpt-001", "fixture-retry", "fixture only"))
    assert result["job"]["id"] == record["id"]
    assert len(list(lab.simulator.spool.glob("jobs/*/request.json"))) == 1


# ---- waiting experiments yield model capacity and retry one background task ---
def test_new_request_freezes_explicit_execution_budgets(lab):
    lab.settings = lab.settings.model_copy(
        update={
            "lab_simulation_wait_seconds": 0.01,
            "lab_simulation_timeout_seconds": 900,
            "lab_simulation_case_timeout_seconds": 480,
        }
    )
    worker_heartbeat(lab)

    async def exercise():
        try:
            queued = await lab.simulator.evaluate("gpt-001", "fixture-budget")
            assert queued["pending"]
            path = lab.simulator.spool / "jobs" / queued["job_id"] / "request.json"
            request = json.loads(path.read_text(encoding="utf-8"))
            assert request["timeout_seconds"] == 900
            assert request["functional_timeout_seconds"] == 480
            assert request["case_ids"] == lab.simulator.default_cases()
        finally:
            await lab.simulator.close()

    asyncio.run(exercise())


def test_pending_simulation_returns_without_waiting_for_worker_or_duplicating(lab, monkeypatch):
    lab.settings = lab.settings.model_copy(update={"lab_simulation_wait_seconds": 0.01})
    worker_heartbeat(lab)
    record = fixture_receipt(lab, state="queued")

    async def exercise():
        release = asyncio.Event()
        started = []

        async def experiment(*args):
            started.append(args[0])
            await release.wait()
            return {"state": "completed", "fixture_only": True}

        monkeypatch.setattr(lab.simulator, "_experiment", experiment)
        first = await lab.simulator.evaluate("gpt-001", "first")
        retry = await lab.simulator.evaluate("gpt-001", "retry")
        assert first["pending"] and first["job_id"] == record["id"]
        assert retry["job_id"] == first["job_id"]
        assert started == ["gpt-001"] and len(lab.simulator.pending) == 1
        task = next(iter(lab.simulator.pending))
        release.set()
        assert (await task)["fixture_only"]

    asyncio.run(exercise())


# ---- cancellation never overwrites execution or becomes passing evidence -----
@pytest.mark.parametrize("state", ["running", "completed", "failed"])
def test_queue_cancellation_preserves_claimed_and_finished_results(lab, state):
    record = fixture_receipt(lab, state=state)
    path = lab.simulator.spool / "jobs" / record["id"] / "result.json"
    original = path.read_bytes()
    assert not lab.simulator.cancel_queued(record["id"], "gpt-001", "fixture")
    assert path.read_bytes() == original


# ---- an unclaimed request remains auditable after cancellation ---------------
def test_queue_cancellation_is_controller_metadata_and_cannot_qualify(lab):
    record = fixture_receipt(lab, state="queued")
    folder = lab.simulator.spool / "jobs" / record["id"]
    (folder / "result.json").unlink()
    source = (folder / "request.json").read_bytes()
    assert not lab.simulator.cancel_queued(record["id"], "gpt-002", "wrong team")
    assert lab.simulator.cancel_queued(record["id"], "gpt-001", "obsolete fixture")
    result = json.loads((folder / "result.json").read_text())
    assert result["state"] == "cancelled" and result["source"] == "controller"
    assert not result["functional_pass"] and not result["cases"]
    assert (folder / "request.json").read_bytes() == source
    assert lab.simulator.evidence("gpt-001", record["source_sha256"]) is None


# ---- CPU backpressure belongs only to the team awaiting its own experiment ---
def test_pending_own_experiment_does_not_block_another_team(lab, monkeypatch):
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    lab.auto_teams(1, "gpt-api")
    worker_heartbeat(lab)
    fixture_receipt(lab, state="queued")
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture-op")
    lab.swarm.write({"enabled": True, "strategy": "parallel"})
    lab.swarm.tick()
    assert [call[0] for call in calls] == ["gpt-002"]
    assert lab.swarm.status()["progress"]["gpt-001"]["phase"] == "awaiting-own-experiment"


# ---- newer cancelled queue entries cannot hide real ongoing execution --------
def test_current_team_experiment_prefers_running_then_pending_then_latest_result(lab):
    rows = [
        {"id": "cancelled", "team": "gpt-001", "state": "cancelled", "created_at": 4},
        {"id": "completed", "team": "gpt-001", "state": "completed", "created_at": 3},
        {"id": "queued", "team": "gpt-001", "state": "queued", "created_at": 2},
        {"id": "running", "team": "gpt-001", "state": "running", "created_at": 1},
        {"id": "other", "team": "gpt-002", "state": "completed", "created_at": 5},
    ]
    assert lab.simulator.current_experiments(rows)["gpt-001"]["id"] == "running"
    assert lab.simulator.current_experiments(rows[:-2])["gpt-001"]["id"] == "queued"
    assert lab.simulator.current_experiments(rows[:2])["gpt-001"]["id"] == "completed"
    assert lab.simulator.current_experiments(rows)["gpt-002"]["id"] == "other"


# ---- lost worker heartbeats are evidence events, including chronological replay
def test_observer_records_available_then_offline_worker(lab):
    async def observe_once():
        task = asyncio.create_task(lab.simulator.observe())
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    worker_heartbeat(lab)
    asyncio.run(observe_once())
    (lab.simulator.spool / "heartbeat.json").unlink()
    asyncio.run(observe_once())
    events = [e for e in lab.store.events() if e["kind"] == "simulation.worker.updated"]
    assert [e["data"]["available"] for e in events] == [True, False]


# ---- pipeline capacity is actual worker state, not the configured model count -
def test_actual_worker_reports_pipeline_and_profiler_slots_separately(lab):
    worker_heartbeat(lab)
    path = lab.simulator.spool / "heartbeat.json"
    value = json.loads(path.read_text())
    value.update(
        concurrency=2,
        profiling_concurrency=1,
        active_jobs=[{"id": "fixture-job", "team": "gpt-001", "phase": "compile"}],
    )
    path.write_text(json.dumps(value))
    status = lab.simulator.status()
    assert status["available"]
    assert status["concurrency"] == 2
    assert status["profiling_concurrency"] == 1
    assert status["active_jobs"][0]["phase"] == "compile"


# ---- all functional cases and fixed representative profiles share one SHA -----
@pytest.mark.parametrize(
    "missing", [None, "functional", "profile", "mode", "selection", "reference"]
)
def test_two_phase_gate_requires_all_functional_checks_and_representative_profiles(lab, missing):
    record = fixture_receipt(lab)
    folder = lab.simulator.spool / "jobs" / record["id"]
    path = folder / "request.json"
    request = json.loads(path.read_text(encoding="utf-8"))
    profiles = lab.simulator.profile_cases()
    assert len(profiles) == 3
    request.update(evaluation_mode="functional-then-profile", profile_case_ids=profiles)
    record["evaluation_mode"] = request["evaluation_mode"]
    record["reference"] = {"engine": "pytorch-cpu-fp32-v1", "version": "2.14.1+cpu", "threads": 1}
    for case in record["cases"]:
        case.update(validation_kind="functional-pvmodel", profiling_files=[])
        if case["id"] in profiles:
            case.update(profile_pass=True, profiling_files=[{"path": "fixture.csv"}])
    if missing == "functional":
        record["cases"][-1]["pass"] = False
    elif missing == "profile":
        next(c for c in record["cases"] if c["id"] == profiles[0])["profile_pass"] = False
    elif missing == "mode":
        record["evaluation_mode"] = "full-profile"
    elif missing == "selection":
        request["profile_case_ids"] = profiles[1:]
    elif missing == "reference":
        record["reference"]["version"] = "different-reference-version"
    path.write_text(json.dumps(request), encoding="utf-8")
    record["request_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (folder / "result.json").write_text(json.dumps(record), encoding="utf-8")
    proof = lab.simulator.evidence(record["team"], record["source_sha256"], require_coverage=True)
    assert bool(proof) == (missing is None)


# ---- dashboard summaries preserve proof identity without embedding profiler files ----
def test_dashboard_receipts_are_small_and_raw_details_remain_intact(lab):
    record = fixture_receipt(lab)
    folder = lab.simulator.spool / "jobs" / record["id"]
    record["cases"][0]["profiling_files"] = [{"preview": "large-private-profile" * 50000}]
    record["cases"][0]["profile_pass"] = True
    (folder / "result.json").write_text(json.dumps(record), encoding="utf-8")
    summary = lab.simulator.jobs(record["team"], summary=True)[0]
    assert len(json.dumps(summary)) < 10000
    assert summary["source_sha256"] == record["source_sha256"]
    assert summary["case_pack_sha256"] == record["case_pack_sha256"]
    assert summary["cases"][0]["profile_pass"] is True
    assert "profiling_files" not in summary["cases"][0]
    assert "files" not in summary and "cases_json" not in summary
    summary["cases"][0]["pass"] = False
    assert lab.simulator.jobs(record["team"], summary=True)[0]["cases"][0]["pass"] is True
    assert lab.simulator.jobs(record["team"])[0]["cases"][0]["profiling_files"][0]["preview"]
    record["state"] = "failed"
    (folder / "result.json").write_text(json.dumps(record), encoding="utf-8")
    assert lab.simulator.jobs(record["team"], summary=True)[0]["state"] == "failed"


# ---- full local success reaches the independent official lane without a new coding turn ----
def test_observer_freezes_completed_current_source_once_without_self_approving(lab):
    async def exercise():
        record = fixture_receipt(lab)
        assert lab.simulator.ready_for_handoff(record)
        short = {**record, "cases": record["cases"][:2]}
        assert not lab.simulator.ready_for_handoff(short)
        assert not lab.simulator.ready_for_handoff({**record, "source_sha256": "stale-source"})
        assert not lab.simulator.ready_for_handoff({**record, "case_pack_sha256": "stale-pack"})
        await lab.simulator.start()
        try:
            for _ in range(80):
                queue = lab.judger.read("queue.json", [])
                if queue:
                    break
                await asyncio.sleep(0.05)
            assert len(queue) == 1
            assert queue[0]["source_sha256"] == record["source_sha256"]
            assert queue[0]["simulation_job_id"] == record["id"]
            assert not queue[0].get("review")
            assert not queue[0].get("official_submission_id")
            assert lab.judger.automation.readiness(queue[0], require_review=False)[0]
            assert not lab.judger.automation.readiness(queue[0])[0]
        finally:
            await lab.simulator.close()
        await lab.simulator.start()
        try:
            await asyncio.sleep(0.1)
            assert len(lab.judger.read("queue.json", [])) == 1
        finally:
            await lab.simulator.close()

    asyncio.run(exercise())

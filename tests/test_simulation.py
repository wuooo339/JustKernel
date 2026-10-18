"""Local protocol fixtures only. These tests never claim real simulation or official scores."""

import asyncio
import hashlib
import json
import time
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
    lab.swarm.write({"enabled": True})
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

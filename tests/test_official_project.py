"""Official project integrity, source-only team PK and public Judge evidence."""

import asyncio
import json
import zipfile

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from pydantic import SecretStr

from aworker.config import Settings
from aworker.lab.deepagent import DeepAgentRuntime
from aworker.lab.judger import JudgeMonitor
from aworker.lab.project import project_manifest
from aworker.lab.service import LabService


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture
def lab(tmp_path):
    service = LabService(
        Settings(
            lab_root=tmp_path / "lab",
            lab_private_root=tmp_path / "private",
            lab_provider_keys={"openai": SecretStr("fixture")},
            lab_team_concurrency=2,
            _env_file=None,
        )
    )
    service.auto_teams(1, "gpt-api")
    return service


# ---- exact official empty project and protected files -----------------------
def test_new_default_is_official_confusion_project_with_provisional_inputs(lab):
    assert lab.operator == "ConfusionMulGrad"
    assert [row["id"] for row in lab.catalog.catalog()] == ["ConfusionMulGrad"]
    assert lab.runner is None
    team = lab.team_folder("gpt-001")
    assert not (team / "kernel.asc").exists()
    manifest = project_manifest(lab.root)
    assert len(manifest["project_files"]) == 34
    assert len(manifest["editable_paths"]) == 7
    assert lab.candidate("gpt-001")["sha256"] == manifest["baseline_sha256"]
    assert manifest["input_source"]["official_case_count"] == 15
    cases = json.loads((team / "cases.json").read_text(encoding="utf-8"))
    assert len(cases) == 15
    assert all(case["official_case_id"] is None for case in cases)
    # The old [-1, 1) pack hid numerical errors at the published input magnitude.
    value_range = manifest["input_source"]["official_value_range"]
    assert value_range == {"low": -10.0, "high": 10.0, "upper_exclusive": True}
    assert all(
        case["distribution"] == {"kind": "uniform", "low": -10.0, "high": 10.0} for case in cases
    )
    assert "positions" not in (team / "CONSTRAINTS.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="unchanged"):
        lab.judger.stage("gpt-001")


def test_source_bundle_preserves_tests_and_zip_has_an_exact_candidate_identity(lab):
    folder = lab.team_folder("gpt-001")
    path = folder / "project/op_kernel/confusion_mul_grad.h"
    path.write_bytes(path.read_bytes() + b"\n// fixture edit; not a validated implementation\n")
    candidate = lab.candidate("gpt-001")
    row = lab.judger.stage("gpt-001")
    assert lab.judger.stage("gpt-001")["id"] == row["id"]
    assert lab.judger.code(row["id"])["files"] == candidate["files"]
    assert row["source_sha256"] == candidate["sha256"]
    assert row["official_submission_id"] is None
    assert not row["policy_certified"]
    with zipfile.ZipFile(lab.judger.package(row["id"])) as archive:
        assert len(archive.namelist()) == 34
        assert (
            archive.read("code/op_kernel/confusion_mul_grad.h").decode()
            == candidate["files"]["op_kernel/confusion_mul_grad.h"]
        )
    protected = folder / "project/build.sh"
    protected.write_bytes(protected.read_bytes() + b"\n# untrusted fixture change\n")
    with pytest.raises(ValueError, match="protected"):
        lab.candidate("gpt-001")


def test_official_feedback_requires_real_result_current_code_and_one_dispatch(lab, monkeypatch):
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_bytes(path.read_bytes() + b"\n// fixture feedback candidate\n")
    row = lab.judger.stage("gpt-001")
    with pytest.raises(ValueError, match="official submission result"):
        lab.judger.feedback(row["id"])
    queue = lab.judger.read("queue.json", [])
    queue[0].update(official={"status": "Fail", "score": 0}, official_submission_id="123456")
    lab.judger.write("queue.json", queue)
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture-op")
    assert lab.judger.feedback(row["id"])["operation_id"] == "fixture-op"
    assert "123456" in calls[0][2]
    with pytest.raises(ValueError, match="already"):
        lab.judger.feedback(row["id"])


def test_judge_network_wait_cannot_drop_newly_staged_candidates(lab):
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_bytes(path.read_bytes() + b"\n// fixture first\n")
    first = lab.judger.stage("gpt-001")
    lab.judger.track(first["id"], "123456")
    problem_id = project_manifest(lab.root)["input_source"]["problem_id"]

    def response(request):
        path.write_bytes(path.read_bytes() + b"\n// fixture concurrent change\n")
        lab.judger.stage("gpt-001")
        return httpx.Response(200, json={"problem_id": problem_id, "status": "Fail", "score": 0})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            await JudgeMonitor(lab, client).refresh_tracked([])

    asyncio.run(scenario())
    queue = lab.judger.read("queue.json", [])
    assert len(queue) == 2
    assert queue[0]["official"]["status"] == "Fail"
    assert queue[1]["official_submission_id"] is None


# ---- actual graph admission scheduling; no paid model calls -----------------
def test_independent_sqlite_memory_survives_parallel_real_graph_writes(lab):
    lab.auto_teams(7, "gpt-api")
    teams = [t["id"] for t in lab.store.snapshot()["teams"]]

    async def one(team):
        path = DeepAgentRuntime(lab, team, "fixture").checkpoint_path()
        assert path.is_absolute()
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            builder = StateGraph(int)
            builder.add_node("increment", lambda x: x + 1)
            builder.set_entry_point("increment")
            builder.set_finish_point("increment")
            graph = builder.compile(checkpointer=saver)
            assert await graph.ainvoke(1, {"configurable": {"thread_id": team}}) == 2
        return path

    async def scenario():
        paths = await asyncio.gather(*(one(team) for team in teams))
        assert len(set(paths)) == 8

    asyncio.run(scenario())


def test_swarm_admission_runs_distinct_teams_with_bounded_concurrency(lab, monkeypatch):
    lab.auto_teams(3, "gpt-api")
    active, maximum = 0, 0

    async def scenario():
        nonlocal active, maximum
        gate = asyncio.Event()
        entered = asyncio.Event()

        async def run(runtime, prompt):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                entered.set()
            await gate.wait()
            active -= 1
            return "fixture graph completed"

        monkeypatch.setattr(DeepAgentRuntime, "run", run)
        teams = [t["id"] for t in lab.store.snapshot()["teams"]]
        with pytest.raises(ValueError):
            lab.start_swarm(teams + ["missing"], "fixture task")
        assert not lab.store.snapshot()["operations"]
        result = lab.start_swarm(teams, "fixture task")
        assert len(result["operations"]) == 4
        await asyncio.wait_for(entered.wait(), 5)
        assert active == 2
        gate.set()
        await asyncio.gather(*list(lab._operations.values()))
        assert all(o["state"] == "completed" for o in lab.store.snapshot()["operations"])

    asyncio.run(scenario())
    assert maximum == 2


# ---- real HTTP client protocol with an explicit local server fixture --------
def test_judger_public_snapshot_and_manual_binding_do_not_fabricate_submissions(lab):
    problem_id = project_manifest(lab.root)["input_source"]["problem_id"]
    source = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    source.write_bytes(source.read_bytes() + b"\n// fixture candidate\n")
    staged = lab.judger.stage("gpt-001")
    lab.judger.track(staged["id"], "123456")
    requests = []

    def official_fixture(request):
        requests.append((request.method, request.url.path))
        if request.url.path.endswith("/ranking"):
            return httpx.Response(
                200,
                json={
                    "total": 1,
                    "pages": 1,
                    "current": 1,
                    "rows": [
                        {
                            "rank": 2,
                            "submission_id": "a" * 24,
                            "submission": {"ID": 123456},
                            "status": "Pass",
                            "score": 7.5,
                            "result": [],
                            "user": {"email": "fixture-private-user"},
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "_id": problem_id,
                "title": "ConfusionMulGrad",
                "desc": "fixture public description",
                "testcases": [],
            },
        )

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(official_fixture)) as client:
            monitor = JudgeMonitor(lab, client)
            await monitor.sync()
            await monitor.sync()
            state = monitor.status()
            assert state["queue"][0]["official"]["score"] == 7.5
            assert state["queue"][0]["binding"] == "user-reported"
            assert not state["automatic_submission"]
            assert "fixture-private-user" not in json.dumps(state)

    asyncio.run(scenario())
    assert all(method == "GET" for method, _ in requests)
    events = lab.store.events()
    assert sum(e["kind"] == "judge.public.updated" for e in events) == 1
    assert not any(e["kind"] == "evaluation.completed" for e in events)

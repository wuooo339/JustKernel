"""Public session and lossless official-feedback contracts; no paid calls or submissions."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from starlette.testclient import TestClient
from test_judge_automation import lab as lab
from test_unified_lab import ScriptedModel
from test_unified_lab import service as service

from aworker.lab.api import create_lab_app
from aworker.lab.deepagent import DeepAgentRuntime
from aworker.lab.receipts import official_case_results
from aworker.lab.tools import EngineeringTools


# ---- paginated sessions exclude other teams, raw harness and private reasoning ----
def test_conversation_pagination_and_projection(service):
    ids = []
    for i in range(7):
        ids.append(
            service.store.event("team-a", "agent.message", text=str(i), reasoning_content="PRIVATE")
        )
        service.store.event("other-team", "agent.message", text="OTHER")
        service.store.event("team-a", "harness.event", secret="HIDDEN")
        service.store.event("team-a", "model.output.delta", text="partial")
    page = service.store.conversation("team-a", limit=3)
    assert [e["seq"] for e in page["events"]] == ids[-3:]
    assert page["has_more"]
    older = service.store.conversation("team-a", page["next_before"], 3)
    assert [e["seq"] for e in older["events"]] == ids[1:4]
    final = service.store.conversation("team-a", older["next_before"], 3)
    assert [e["seq"] for e in final["events"]] == ids[:1]
    assert not final["has_more"]
    assert "PRIVATE" not in json.dumps(page)
    for team in ["../outside", "missing"]:
        with pytest.raises(ValueError):
            service.store.conversation(team)
    with pytest.raises(ValueError):
        service.store.conversation("team-a", 0)
    with TestClient(create_lab_app(service)) as client:
        response = client.get("/api/lab/control/teams/team-a/conversation?limit=3")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "PRIVATE" not in response.text


# ---- an explanation cannot claim validation or reset the progress guard ----
def test_public_progress_does_not_modify_source_or_validation(service, monkeypatch):
    tool = next(
        t
        for t in EngineeringTools(service, "team-a", "run", service.team_folder("team-a")).build()
        if t.name == "report_progress"
    )
    source = service.candidate("team-a")["sha256"]
    monkeypatch.setattr(service, "redact", lambda text: text.replace("private-key", "[REDACTED]"))
    result = json.loads(
        tool.invoke({"summary": "Observed failure, private-key", "next_action": "Run a diagnostic"})
    )
    assert result["published"]
    assert "private-key" not in json.dumps(service.store.events())
    assert service.candidate("team-a")["sha256"] == source
    assert service.iterations.read("team-a") is None
    assert not service.store.snapshot()["jobs"]
    with pytest.raises(ValueError):
        tool.invoke({"summary": "x"})


# ---- Judger history includes actual receipts without importing team calls ----
def test_judger_session_cross_team_receipts(service):
    service.store.event("controller", "agent.message", text="public review", reasoning="PRIVATE")
    service.store.event("team-a", "tool.started", tool="edit_file", input="TEAM EDIT")
    service.store.event("team-a", "judge.submitted", submission_id="official-id")
    service.store.event("team-a", "judge.submission.updated", official={"status": "Wrong Answer"})
    page = service.store.conversation("controller")
    text = json.dumps(page)
    assert "public review" in text and "official-id" in text and "Wrong Answer" in text
    assert "PRIVATE" not in text and "TEAM EDIT" not in text


# ---- read-only reviewer streams public text/tools, never private blocks ------
def test_judge_observer_public_projection(service):
    from aworker.lab.public_session import JudgeSession

    observer = JudgeSession(service, "fixture")
    observer.start()
    observer.observe({"event": "on_chat_model_start", "run_id": "m"})
    observer.observe(
        {
            "event": "on_chat_model_end",
            "run_id": "m",
            "data": {
                "output": AIMessage(
                    "Public decision", additional_kwargs={"reasoning_content": "PRIVATE"}
                )
            },
        }
    )
    observer.observe(
        {
            "event": "on_tool_start",
            "run_id": "t",
            "name": "read_candidate",
            "data": {"input": {"candidate_id": "frozen"}},
        }
    )
    observer.observe(
        {
            "event": "on_tool_end",
            "run_id": "t",
            "name": "read_candidate",
            "data": {"output": "Actual source"},
        }
    )
    observer.finish()
    events = service.store.conversation("controller")["events"]
    assert "PRIVATE" not in json.dumps(events)
    tool = next(e["data"] for e in events if e["kind"] == "tool.completed")
    assert tool["model_call_id"] == "m" and tool["output"] == "Actual source"


# ---- actual observer binds tools/diffs to their model call and measured duration ----
def test_observer_records_actual_diff_and_not_private_reasoning(service):
    runtime = DeepAgentRuntime(service, "team-a", "round")
    runtime.observable({"event": "on_chat_model_start", "run_id": "m", "name": "fixture"})
    runtime.observable(
        {
            "event": "on_chat_model_end",
            "run_id": "m",
            "name": "fixture",
            "data": {
                "output": AIMessage("public", additional_kwargs={"reasoning_content": "PRIVATE"})
            },
        }
    )
    folder = service.team_folder("team-a")
    before = service.candidate("team-a")["sha256"]
    runtime.observable(
        {
            "event": "on_tool_start",
            "run_id": "edit",
            "name": "edit_file",
            "data": {"input": {"file_path": "/kernel.asc"}},
        }
    )
    code = folder / "kernel.asc"
    code.write_text(
        code.read_text(encoding="utf-8") + "\n// actual fixture edit\n", encoding="utf-8"
    )
    runtime.observable(
        {
            "event": "on_tool_end",
            "run_id": "edit",
            "name": "edit_file",
            "data": {"output": "edited"},
        }
    )
    events = service.store.events()
    patch = next(e["data"] for e in events if e["kind"] == "workspace.patch")
    assert "+// actual fixture edit" in patch["patch"]
    assert patch["source_before"] == before
    assert patch["source_sha256"] == service.candidate("team-a")["sha256"]
    assert next(e["data"] for e in events if e["kind"] == "tool.started")["model_call_id"] == "m"
    assert next(e["data"] for e in events if e["kind"] == "model.completed")["duration_ms"] >= 0
    assert "PRIVATE" not in json.dumps(events)
    count = len([e for e in events if e["kind"] == "workspace.patch"])
    runtime.observable(
        {
            "event": "on_tool_start",
            "run_id": "protected",
            "name": "edit_file",
            "data": {"input": {"file_path": "/cases.json"}},
        }
    )
    runtime.observable(
        {
            "event": "on_tool_error",
            "run_id": "protected",
            "name": "edit_file",
            "data": {"error": "permission denied"},
        }
    )
    assert len([e for e in service.store.events() if e["kind"] == "workspace.patch"]) == count


# ---- the real graph can publish progress and continue directly editing ----
def test_graph_public_update_and_file_edit_are_continuous(service, monkeypatch):
    code = service.team_folder("team-a") / "kernel.asc"
    original = code.read_text(encoding="utf-8").splitlines()[0]
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "progress",
                        "name": "report_progress",
                        "args": {
                            "summary": "Fixture observation; checking source",
                            "next_action": "Edit the fixture",
                        },
                    }
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "edit",
                        "name": "edit_file",
                        "args": {
                            "file_path": "/kernel.asc",
                            "old_string": original,
                            "new_string": "// fixture public-session edit",
                        },
                    }
                ],
            ),
            AIMessage("Fixture edit finished; no execution result claimed."),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    answer = asyncio.run(service.run_team("team-a", "Test public work session"))
    assert "Fixture edit finished" in answer
    events = service.store.events()
    assert any(e["kind"] == "agent.progress" for e in events)
    assert any(e["kind"] == "workspace.patch" for e in events)
    assert len([e for e in events if e["kind"] == "model.completed"]) == 3


# ---- full official evidence reaches tools, controller and A2A without truncation ----
def test_complete_official_case_feedback(lab, monkeypatch):
    cases = [
        {
            "testcase_id": f"official-{i}",
            "testcase_status": "Wrong Answer" if i in (9, 12, 14) else "Pass",
            "precision_ratio": 0.999 if i in (9, 12, 14) else 1.0,
            "time": 44000 if i == 11 else 6.72,
            "best_time": 1680 if i == 11 else 5.76,
        }
        for i in range(1, 16)
    ]
    ids = [c["testcase_id"] for c in cases]
    official = {"status": "Wrong Answer", "score": None, "result": cases}
    source = lab.candidate("gpt-001")["sha256"]
    row = {
        "id": "fixture-candidate",
        "team": "gpt-001",
        "source_sha256": source,
        "created": 1,
        "submitted_at": 1,
        "official_submission_id": "a" * 24,
        "official": official,
    }
    lab.judger.write("queue.json", [row])
    lab.judger.write("latest.json", {"official_testcase_ids": ids})
    normalized = official_case_results(official, ids)
    assert len(normalized) == 15
    assert normalized[10]["time_us"] == 44000
    assert normalized[10]["best_time_us"] == 1680
    assert normalized[8]["error_percent"] == pytest.approx(0.1)
    assert normalized[7]["error_percent"] == 0
    task = lab.iterations.sync("gpt-001")
    assert task["evidence"]["official_case_results"] == normalized
    detailed = lab.judger.model_status("gpt-001")["queue"][0]
    assert detailed["official_case_results"] == normalized
    monkeypatch.setattr(lab.simulator, "can_learn", lambda team: False)
    tools = EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001")).build()
    observed = json.loads(next(t for t in tools if t.name == "read_judge_status").invoke({}))
    assert observed["own_official"][0]["official_case_results"] == normalized
    lab.judger.broadcast_feedback()
    notice = next(n for n in lab.judger.notices.read() if n.topic == "judge-feedback")
    payload = json.JSONDecoder().raw_decode(notice.message.split("：", 1)[1])[0]
    assert payload["official_case_results"] == normalized
    assert payload["source_sha256"] == source
    assert payload["official_submission_id"] == "a" * 24
    assert len(notice.message) < 8000
    lab.judger.broadcast_feedback()
    assert len([n for n in lab.judger.notices.read() if n.topic == "judge-feedback"]) == 1


# ---- upgrading evidence fields must preserve a team's in-flight plan --------
def test_receipt_enrichment_preserves_work_item_and_plan(lab):
    task = lab.iterations.sync("gpt-001")
    task["evidence"].pop("official_case_results")
    task["evidence"].pop("official_time_unit")
    task["phase"] = "awaiting-experiment"
    task["plan"] = {"hypothesis": "fixture in-flight plan", "jobs": []}
    lab.iterations.write(task)
    # Exercise enrichment only: the reconciliation protocol is independently covered.
    from unittest.mock import patch

    with patch.object(
        lab.iterations, "reconcile", side_effect=lambda team: lab.iterations.read(team)
    ):
        enriched = lab.iterations.sync("gpt-001")
    assert enriched["id"] == task["id"]
    assert enriched["phase"] == "awaiting-experiment"
    assert enriched["plan"] == task["plan"]
    assert enriched["evidence"]["official_time_unit"] == "us"


# ---- no made-up zeros, coercions or unofficial input mappings ----
def test_receipt_missing_and_invalid_fields_stay_unknown():
    rows = official_case_results(
        {
            "result": [
                {
                    "testcase_id": "b",
                    "testcase_status": "Pass",
                    "precision_ratio": 2,
                    "time": None,
                    "best_time": "12",
                },
                {"testcase_id": "a", "precision_ratio": 0, "time": 0, "best_time": float("nan")},
            ]
        },
        ["a", "b"],
    )
    assert rows[0]["number"] == 1
    assert rows[0]["error_percent"] == 100
    assert rows[0]["time_us"] == 0
    assert rows[0]["best_time_us"] is None
    assert rows[1]["error_percent"] is None
    assert rows[1]["best_time_us"] is None

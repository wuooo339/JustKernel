"""Evidence-based stop and real tool normalization/permission regression tests."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from test_unified_lab import ScriptedModel
from test_unified_lab import service as service

from aworker.lab.progress import BaselineProgressGuard
from aworker.lab.tool_arguments import normalize_arguments


# ---- idle clocks and response limits require code or a new experiment -------
def test_reads_and_repeated_old_jobs_cannot_keep_a_turn_alive():
    now = [0]
    guard = BaselineProgressGuard(
        "original", ["old-job"], seconds=300, calls=12, clock=lambda: now[0]
    )
    for i in range(11):
        guard.observe(source="original", jobs=["old-job"], call=str(i))
    now[0] = 300
    with pytest.raises(RuntimeError, match="BASELINE_NO_PROGRESS"):
        guard.observe(source="original", jobs=["old-job"])


def test_code_change_or_new_job_resets_guard_but_duplicate_callbacks_do_not_count():
    guard = BaselineProgressGuard("old", calls=2)
    guard.observe(call="one")
    guard.observe(call="one")
    guard.observe(source="new")
    guard.observe(call="two")
    guard.observe(jobs=["fresh-job"])
    guard.observe(call="three")
    with pytest.raises(RuntimeError, match="BASELINE_NO_PROGRESS"):
        guard.observe(call="four")


# ---- actual graph stops analysis-only writes without changing source ---------
def test_baseline_graph_stops_after_analysis_only_without_spending_more_calls(service, monkeypatch):
    service.settings.lab_baseline_idle_calls = 2
    service.swarm.write({"enabled": True, "strategy": "baseline", "main_team": "team-a"})
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "analysis",
                        "name": "write_file",
                        "args": {"file_path": "/analysis.txt", "content": "fixture notes"},
                    }
                ],
            ),
            AIMessage(
                "",
                tool_calls=[{"id": "read", "name": "read_file", "args": {"file_path": "/TEAM.md"}}],
            ),
            *[
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "id": "repeat-" + str(i),
                            "name": "read_file",
                            "args": {"file_path": "/TEAM.md"},
                        }
                    ],
                )
                for i in range(2)
            ],
            AIMessage("should never be called"),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    original = service.candidate("team-a")["sha256"]
    with pytest.raises(RuntimeError, match="BASELINE_NO_PROGRESS"):
        asyncio.run(service.run_team("team-a", "fixture idle turn"))
    assert len(model.responses) == 1
    assert service.candidate("team-a")["sha256"] == original
    assert (service.team_folder("team-a") / "analysis.txt").exists()
    assert service.store.snapshot()["runs"][0]["state"] == "failed"
    assert any(e["kind"] == "baseline.progress.warning" for e in service.store.events())


# ---- allow the final response's real source edit before checking another call --
def test_final_allowed_response_can_edit_before_the_next_call_is_checked(service, monkeypatch):
    service.settings.lab_baseline_idle_calls = 2
    service.swarm.write({"enabled": True, "strategy": "baseline", "main_team": "team-a"})
    path = service.team_folder("team-a") / "kernel.asc"
    original = path.read_text(encoding="utf-8")
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {"id": "read", "name": "read_file", "args": {"file_path": "/kernel.asc"}}
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
                            "new_string": original + "\n// fixture source change\n",
                        },
                    }
                ],
            ),
            AIMessage("fixture complete"),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    assert (
        asyncio.run(service.run_team("team-a", "fixture last allowed edit")) == "fixture complete"
    )
    assert "fixture source change" in path.read_text(encoding="utf-8")


# ---- aliases still pass through the same permission boundary ----------------
def test_tool_aliases_preserve_protected_files_and_private_read_denials(service, monkeypatch):
    folder = service.team_folder("team-a")
    (folder / ".env.fixture").write_text("private-fixture-value", encoding="utf-8")
    (folder / "read-fixture.txt").write_text("public-fixture-value", encoding="utf-8")
    before = (folder / "cases.json").read_bytes()
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {"id": "read", "name": "read_file", "args": {"path": "/read-fixture.txt"}}
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {"id": "secret", "name": "read_file", "args": {"path": "/.env.fixture"}}
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "protected",
                        "name": "write_file",
                        "args": {"path": "/cases.json", "content": "[]"},
                    }
                ],
            ),
            AIMessage("fixture finished"),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    assert asyncio.run(service.run_team("team-a", "fixture aliases")) == "fixture finished"
    assert (folder / "cases.json").read_bytes() == before
    events = service.store.events()
    assert "private-fixture-value" not in json.dumps(events)
    assert any(e["kind"] == "tool.arguments.normalized" for e in events)
    assert any(
        e["kind"] == "tool.completed" and "public-fixture-value" in e["data"].get("output", "")
        for e in events
    )


# ---- parse only JSON arrays of strings, never arbitrary Python expressions ---
def test_stringified_arguments_are_narrowly_normalized_without_mutation():
    args = {"script_path": "analysis.py", "arguments": '["a", "b"]'}
    assert normalize_arguments("run_python", args)["arguments"] == ["a", "b"]
    assert isinstance(args["arguments"], str)
    for value in ("__import__('os')", '{"a":1}', "[1]"):
        assert normalize_arguments("run_python", {"arguments": value})["arguments"] == value


# ---- one finite correction opportunity, never an endless reset on log reads ----
def test_idle_guard_warns_once_then_stops_and_code_progress_resets_it():
    now = [0]
    guard = BaselineProgressGuard(
        "source", calls=2, grace_calls=2, seconds=300, clock=lambda: now[0]
    )
    guard.observe(call="1")
    assert "BASELINE_PROGRESS_CHECK" in guard.observe(call="2")
    assert guard.observe(call="3") is None
    with pytest.raises(RuntimeError, match="BASELINE_NO_PROGRESS"):
        guard.observe(call="4")
    assert guard.observe(source="changed") is None
    assert not guard.warned and not guard.completed_calls
    now[0] = 300
    with pytest.raises(RuntimeError, match="BASELINE_NO_PROGRESS"):
        guard.observe()


# ---- real graph receives correction and can edit without losing its workspace ----
def test_baseline_graph_can_correct_after_read_budget_warning(service, monkeypatch):
    service.settings.lab_baseline_idle_calls = 2
    service.swarm.write({"enabled": True, "strategy": "baseline", "main_team": "team-a"})
    path = service.team_folder("team-a") / "kernel.asc"
    original = path.read_text(encoding="utf-8")
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "read-" + str(i),
                        "name": "read_file",
                        "args": {"file_path": "/kernel.asc"},
                    }
                ],
            )
            for i in range(2)
        ]
        + [
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "edit",
                        "name": "edit_file",
                        "args": {
                            "file_path": "/kernel.asc",
                            "old_string": original,
                            "new_string": original + "\n// corrected fixture implementation\n",
                        },
                    }
                ],
            ),
            AIMessage("Fixture correction complete."),
        ]
    )
    seen = []
    generate = ScriptedModel._generate

    def capture(self, messages, *args, **kwargs):
        seen.extend(str(m.content) for m in messages if "BASELINE_PROGRESS_CHECK" in str(m.content))
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedModel, "_generate", capture)
    monkeypatch.setattr(service.registry, "build", lambda _: model)
    assert (
        asyncio.run(service.run_team("team-a", "Fixture correct after warning"))
        == "Fixture correction complete."
    )
    assert seen
    assert "corrected fixture implementation" in path.read_text(encoding="utf-8")


# ---- streamed planning is allowed to finish its edit before the next idle checkpoint ----
def test_inflight_generation_can_finish_a_real_edit_after_idle_time(service, monkeypatch):
    import aworker.lab.deepagent as runtime

    now = [0]
    guard = BaselineProgressGuard

    def controlled_guard(*args, **kwargs):
        return guard(*args, **kwargs, clock=lambda: now[0])

    monkeypatch.setattr(runtime, "BaselineProgressGuard", controlled_guard)
    service.swarm.write({"enabled": True, "strategy": "baseline", "main_team": "team-a"})
    path = service.team_folder("team-a") / "kernel.asc"
    original = path.read_text(encoding="utf-8")
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "edit",
                        "name": "edit_file",
                        "args": {
                            "file_path": "/kernel.asc",
                            "old_string": original,
                            "new_string": original + "\n// completed long response edit\n",
                        },
                    }
                ],
            ),
            AIMessage("Long response fixture complete."),
        ]
    )
    generate = ScriptedModel._generate

    def long_generate(self, messages, *args, **kwargs):
        now[0] = service.settings.lab_baseline_idle_seconds * 2 + 1
        return generate(self, messages, *args, **kwargs)

    monkeypatch.setattr(ScriptedModel, "_generate", long_generate)
    monkeypatch.setattr(service.registry, "build", lambda _: model)
    assert (
        asyncio.run(service.run_team("team-a", "Fixture long generation"))
        == "Long response fixture complete."
    )
    assert "completed long response edit" in path.read_text(encoding="utf-8")


# ---- generator scripts count only when they actually change operator source ----
def test_python_source_generation_resets_progress_but_not_analysis_notes(service, monkeypatch):
    service.settings.lab_baseline_idle_calls = 2
    service.swarm.write({"enabled": True, "strategy": "baseline", "main_team": "team-a"})
    folder = service.team_folder("team-a")
    (folder / "generate.py").write_text(
        'from pathlib import Path\np=Path("kernel.asc")\n'
        'p.write_text(p.read_text(encoding="utf-8")+'
        '"\\n// generated fixture implementation\\n",encoding="utf-8")\n',
        encoding="utf-8",
    )
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {"id": "read", "name": "read_file", "args": {"file_path": "/kernel.asc"}}
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "generate",
                        "name": "run_python",
                        "args": {"script_path": "/generate.py"},
                    }
                ],
            ),
            AIMessage("Fixture generated source complete."),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda _: model)
    assert (
        asyncio.run(service.run_team("team-a", "Fixture generator"))
        == "Fixture generated source complete."
    )
    assert "generated fixture implementation" in (folder / "kernel.asc").read_text(encoding="utf-8")
    assert not any(e["kind"] == "baseline.progress.warning" for e in service.store.events())


# ---- compatible providers may stringify typed arrays; never drop the requested subset ----
def test_simulation_and_plan_arrays_are_normalized_narrowly():
    data = {"case_ids": '["draft-01"]', "learned_from": '["artifact-a"]'}
    normalized = normalize_arguments("simulate_kernel", data)
    assert normalized == {"case_ids": ["draft-01"], "learned_from": ["artifact-a"]}
    assert isinstance(data["case_ids"], str)
    assert normalize_arguments("simulate_kernel", {"case_ids": "[1]"})["case_ids"] == "[1]"
    assert (
        normalize_arguments("simulate_kernel", {"case_ids": '__import__("os")'})["case_ids"]
        == '__import__("os")'
    )
    assert normalize_arguments(
        "write_todos", {"todos": '[{"content":"fixture","status":"pending"}]'}
    )["todos"] == [{"content": "fixture", "status": "pending"}]


# ---- real graph reaches the simulator with exactly the requested parsed case IDs ----
def test_graph_simulation_stringified_subset_never_silently_becomes_all_cases(service, monkeypatch):
    calls = []

    async def evaluate(team, run_id, hypothesis, case_ids, learned_from):
        calls.append((case_ids, learned_from))
        return {"pending": True, "job_id": "fixture-job-not-real-execution", "state": "queued"}

    monkeypatch.setattr(service.simulator, "evaluate", evaluate)
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "probe",
                        "name": "simulate_kernel",
                        "args": {
                            "hypothesis": "explicit protocol fixture",
                            "case_ids": '["draft-01"]',
                            "learned_from": "[]",
                        },
                    }
                ],
            ),
            AIMessage("Fixture probe queued, no real execution claimed."),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda _: model)
    assert (
        asyncio.run(service.run_team("team-a", "Fixture one-case request"))
        == "Fixture probe queued, no real execution claimed."
    )
    assert calls == [(["draft-01"], [])]
    assert not any(e["kind"] == "tool.recoverable_error" for e in service.store.events())

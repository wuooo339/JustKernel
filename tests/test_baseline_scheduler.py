"""Single-team admission and credential-failure stop, without paid model calls."""

import asyncio

from pydantic import SecretStr
from test_judge_automation import lab as lab

from aworker.lab.continuous import SwarmPlan


# ---- one main team even when eight independent workspaces are registered ----
def test_default_baseline_dispatches_only_one_of_eight_teams(lab, monkeypatch):
    lab.auto_teams(7, "gpt-api")
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture")
    lab.swarm.write({"enabled": True, "main_team": "gpt-003"})
    lab.swarm.tick()
    assert [args[0] for args in calls] == ["gpt-003"]
    assert "case_ids" in calls[0][2]
    assert len(lab.store.snapshot()["teams"]) == 8


# ---- switching a main model retains source, history and separate conversation ----
def test_baseline_can_bind_qwen_without_overwriting_existing_work(lab):
    lab.registry.local_keys["qwen-api"] = SecretStr("fixture")
    folder = lab.team_folder("gpt-001")
    previous = lab.candidate("gpt-001")["sha256"]
    lab.store.session("gpt-001", "old-fixture-session")

    async def scenario():
        await lab.swarm.configure(SwarmPlan(enabled=True, main_team="gpt-001", model="qwen-api"))
        await lab.swarm.close()

    asyncio.run(scenario())
    team = lab.store.snapshot()["teams"][0]
    assert team["model"] == "qwen-api" and team["session"] != "old-fixture-session"
    assert lab.candidate("gpt-001")["sha256"] == previous
    assert folder.exists() and lab.swarm.status()["teams"] == ["gpt-001"]


# ---- a terminal billing/auth failure blocks subsequent dispatch until resumption ----
def test_balance_failure_stops_retries_and_explicit_resume_can_try_again(lab, monkeypatch):
    lab.store.operation("fixture-failed", "gpt-001", "run")
    lab.store.operation_finished("fixture-failed", "failed", "Error code: 402 Insufficient Balance")
    lab.swarm.write(
        {"enabled": True, "progress": {"gpt-001": {"operation_id": "fixture-failed", "turns": 1}}}
    )
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture-next")
    lab.swarm.tick()
    lab.swarm.tick()
    assert not calls and not lab.swarm.status()["enabled"]
    assert lab.swarm.status()["blocked_reason"]

    async def scenario():
        await lab.swarm.configure(SwarmPlan(enabled=True, main_team="gpt-001"))
        await lab.swarm.close()

    asyncio.run(scenario())
    # Acknowledged historical failure must not immediately stop the resumed plan.
    lab.swarm.tick()
    assert len(calls) == 1 and lab.swarm.status()["enabled"]

"""Allocate real team workspaces without making model or device calls."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from aworker.config import Settings
from aworker.lab.api import create_lab_app
from aworker.lab.cli import initialize
from aworker.lab.providers import ModelProfile
from aworker.lab.service import LabService


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture
def service(tmp_path):
    lab = LabService(
        Settings(
            lab_root=tmp_path / "lab",
            lab_default_operator="RotaryPosEmb",
            lab_execution_mode="hybrid",
            lab_private_root=tmp_path / "private",
            lab_ssh_host=None,
            lab_provider_keys={"gpt": SecretStr("fixture"), "deepseek": SecretStr("fixture")},
            _env_file=None,
        )
    )
    lab.registry.profiles = {
        key: ModelProfile(name=key, provider=provider, model="fixture", secret=key)
        for key, provider in [("gpt", "openai"), ("deepseek", "deepseek"), ("unused", "glm")]
    }
    return lab


# ---- default allocation and independent workspaces --------------------------
def test_automatic_allocation_balances_only_configured_models(service):
    with TestClient(create_lab_app(service)) as api:
        response = api.post("/api/lab/control/teams/auto", json={"count": 4})
        assert response.status_code == 200
        assert [(t["team"], t["model"]) for t in response.json()["teams"]] == [
            ("gpt-001", "gpt"),
            ("deepseek-001", "deepseek"),
            ("gpt-002", "gpt"),
            ("deepseek-002", "deepseek"),
        ]
        for team in response.json()["teams"]:
            folder = service.team_folder(team["team"])
            assert (folder / "kernel.asc").is_file()
            assert (folder / "TEAM.md").is_file()
        snapshot = api.get("/api/lab/snapshot").json()
        assert len(snapshot["members"]) == 12
        assert not snapshot["operations"] and not snapshot["jobs"] and not snapshot["runs"]


# ---- archival and preflight boundaries -------------------------------------
def test_automatic_names_never_overwrite_retired_sources_or_history(service):
    service.auto_teams(model="gpt")
    folder = service.team_folder("gpt-001")
    (folder / "kernel.asc").write_text("// preserved previous experiment", encoding="utf-8")
    service.store.event("gpt-001", "fixture.evidence", message="preserved evidence")
    service.leave("gpt-001")
    assert service.auto_teams(model="gpt")[0]["team"] == "gpt-002"
    assert (folder / "kernel.asc").read_text(encoding="utf-8") == "// preserved previous experiment"
    assert any(e["kind"] == "fixture.evidence" for e in service.store.events())
    service.settings = service.settings.model_copy(update={"lab_max_teams": 2})
    with TestClient(create_lab_app(service)) as api:
        before = service.store.snapshot()["teams"]
        assert api.post("/api/lab/control/teams/auto", json={"count": 2}).status_code == 409
        assert service.store.snapshot()["teams"] == before
        assert api.post("/api/lab/control/teams/auto", json={"model": "unused"}).status_code == 409
        assert api.post("/api/lab/control/teams/auto", json={"count": 0}).status_code == 422


# ---- concurrent allocation and fresh startup -------------------------------
def test_parallel_allocations_reserve_unique_names_and_balance_models(service):
    service.settings = service.settings.model_copy(update={"lab_max_teams": 8})
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda _: service.auto_teams(count=2), range(4)))
    teams = [team for batch in batches for team in batch]
    assert len({t["team"] for t in teams}) == 8
    assert sum(t["model"] == "gpt" for t in teams) == 4
    assert sum(t["model"] == "deepseek" for t in teams) == 4
    with pytest.raises(ValueError, match="capacity"):
        service.auto_teams()


def test_startup_creates_no_unconfigured_teams_and_does_not_duplicate(service):
    original = service.registry.profiles
    service.registry.profiles = {"unused": original["unused"]}
    initialize(service)
    assert not service.store.snapshot()["teams"]
    service.registry.profiles = original
    initialize(service)
    initialize(service)
    assert len(service.store.snapshot()["teams"]) == 1


# ---- explicit migration keeps work and isolates provider conversation state ---
def test_model_migration_preserves_sources_and_history_with_fresh_session(service):
    service.auto_teams(model="gpt")
    service.store.session("gpt-001", "original-gpt-session")
    folder = service.team_folder("gpt-001")
    code = (folder / "kernel.asc").read_bytes()
    service.store.event("gpt-001", "fixture.previous-work")
    service.rebind_model("gpt-001", "deepseek")
    team = service.store.snapshot()["teams"][0]
    assert team["model"] == "deepseek" and team["session"] != "original-gpt-session"
    assert (folder / "kernel.asc").read_bytes() == code
    assert any(e["kind"] == "fixture.previous-work" for e in service.store.events())
    assert all(m["model"] is None for m in service.store.snapshot()["members"])
    service.rebind_model("gpt-001", "deepseek")
    assert service.store.snapshot()["teams"][0]["session"] == team["session"]


# ---- migration cannot interrupt active work or bind an unconfigured model ----
def test_model_migration_rejects_active_tasks_and_unconfigured_models(service):
    service.auto_teams(model="gpt")
    with pytest.raises(ValueError):
        service.rebind_model("gpt-001", "unused")
    with service.store.connection() as db:
        db.execute(
            "INSERT INTO operations VALUES(?,?,?,?,?,?)",
            ("fixture-op", "gpt-001", "optimize", "running", 0, None),
        )
    with pytest.raises(ValueError, match="active task"):
        service.rebind_model("gpt-001", "deepseek")
    assert service.store.snapshot()["teams"][0]["model"] == "gpt"

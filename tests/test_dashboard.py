"""External browsers must load changed JS even if index.html did not change."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aworker.lab.dashboard import DashboardFiles
from aworker.lab.store import LabStore


# ---- resource version coherence ---------------------------------------------
def test_entry_versions_assets_by_content_and_never_uses_an_old_entry_etag(tmp_path):
    (tmp_path / "index.html").write_text(
        '<link href="styles.css"><script src="app.js"></script>', encoding="utf-8"
    )
    (tmp_path / "styles.css").write_text("body{}", encoding="utf-8")
    script = tmp_path / "app.js"
    script.write_text("const version=1;", encoding="utf-8")
    app = FastAPI()
    app.mount("/", DashboardFiles(tmp_path))
    with TestClient(app) as client:
        first = client.get("/")
        assert first.headers["cache-control"] == "no-store"
        assert len(re.findall(r"\?v=[a-f0-9]{16}", first.text)) == 2
        old_url = re.search(r'src="([^"]+)"', first.text)[1]
        old_asset = client.get("/" + old_url)
        assert old_asset.headers["cache-control"] == "no-cache, must-revalidate"
        script.write_text("const version=2;", encoding="utf-8")
        current = client.get("/", headers={"If-None-Match": '"old-entry"'})
        assert current.status_code == 200
        new_url = re.search(r'src="([^"]+)"', current.text)[1]
        assert new_url != old_url
        assert "version=2" in client.get("/" + new_url).text
        assert client.get("/index.html").text == current.text
        assert client.head("/").content == b""
        assert client.get("/missing.js").status_code == 404


# ---- current dashboard starts at the live cursor, with important context -----
def test_bootstrap_retains_old_official_results_and_team_stages_without_replaying_all(tmp_path):
    store = LabStore(tmp_path / "journal.sqlite3")
    official = store.event(
        "a",
        "judge.submission.updated",
        submission_id="one",
        official={"status": "Wrong Answer", "result": []},
    )
    stage = store.event("a", "stage.updated", stage="execute", state="progress")
    message = store.event("judger", "team.message", recipient="a", transport="a2a")
    with store.connection() as db:
        db.executemany(
            "INSERT INTO events(at,team,kind,data) VALUES(?,?,?,?)",
            [(100, "a", "harness.event", "{}")] * 3000,
        )
    last = store.event("b", "stage.updated", stage="search", state="progress")
    bootstrap = store.dashboard_events(limit=20)
    assert bootstrap["total"] == 3004
    assert bootstrap["cursor"] == last
    assert len(bootstrap["events"]) < 30
    sequences = [e["seq"] for e in bootstrap["events"]]
    assert all(seq in sequences for seq in [official, stage, message, last])
    assert sequences == sorted(set(sequences))
    newer = store.event("b", "agent.message", text="actual next progress")
    assert [e["seq"] for e in store.events(bootstrap["cursor"])] == [newer]
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3005

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from justkernel.bootstrap.cli import main
from justkernel.platform.persistence.database import connect

ROOT = Path(__file__).resolve().parents[2]
LEGACY_NAME = "awork" + "er"


def _old_database(path: Path) -> str:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE teams (id TEXT PRIMARY KEY, runtime TEXT, model TEXT);
        CREATE TABLE members (team TEXT, name TEXT, role TEXT);
        CREATE TABLE runs (id TEXT PRIMARY KEY, team TEXT, state TEXT);
        CREATE TABLE experiences (id TEXT PRIMARY KEY, team TEXT, data TEXT);
        CREATE TABLE events (seq INTEGER PRIMARY KEY, team TEXT, kind TEXT, data TEXT);
        """
    )
    connection.execute("INSERT INTO teams VALUES ('team-1', 'deepagents', 'model-1')")
    connection.execute("INSERT INTO members VALUES ('team-1', 'mentor', 'MENTOR')")
    connection.execute("INSERT INTO runs VALUES ('run-1', 'team-1', 'completed')")
    connection.execute("INSERT INTO experiences VALUES ('exp-1', 'team-1', '{\"score\":1}')")
    connection.execute(
        "INSERT INTO events VALUES (1, 'team-1', 'candidate.selected', '{\"candidate\":\"old\"}')"
    )
    connection.commit()
    connection.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_legacy_migration_is_read_only_idempotent_and_inactive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = tmp_path / "legacy.db"
    digest = _old_database(old)
    data_root = tmp_path / "justkernel"
    command = [
        "--mode",
        "migrate",
        "--data-root",
        str(data_root),
        "--legacy-db",
        str(old),
    ]

    assert main(command) == 0
    first = capsys.readouterr().out
    assert "imported=5" in first
    assert "idempotent=false" in first
    assert hashlib.sha256(old.read_bytes()).hexdigest() == digest

    journal = connect(str(data_root / "journal.db"))
    try:
        assert journal.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0] == 1
        assert journal.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0] == 5
        assert journal.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 0
        assert journal.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
        assert journal.execute("SELECT COUNT(*) FROM board_posts").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            journal.execute("DELETE FROM legacy_records")
    finally:
        journal.close()

    assert main(command) == 0
    second = capsys.readouterr().out
    assert "idempotent=true" in second
    journal = connect(str(data_root / "journal.db"))
    try:
        assert journal.execute("SELECT COUNT(*) FROM legacy_imports").fetchone()[0] == 1
        assert journal.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0] == 5
    finally:
        journal.close()


def test_new_package_demo_compatibility(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--mode", "demo", "--data-root", str(tmp_path / "demo")]) == 0
    assert "mode=demo" in capsys.readouterr().out
    assert (ROOT / "pyproject.toml").read_text(encoding="utf-8").count("justkernel") >= 1
    fixture = json.loads(
        (ROOT / "src" / "justkernel" / "web" / "demo" / "fixture.json").read_text(encoding="utf-8")
    )
    assert fixture["meta"]["model_calls"] == 0
    assert fixture["meta"]["device_calls"] == 0

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for demo replay")
    fixture_url = (ROOT / "src" / "justkernel" / "web" / "demo" / "fixture.js").as_uri()
    script = (
        f"import {{ DEMO_STATE }} from {json.dumps(fixture_url)};"
        "console.log(JSON.stringify(DEMO_STATE));"
    )
    state = json.loads(
        subprocess.run(
            [node, "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert state["clusters"]["demo-cluster"]["state"] == "COMPLETED"
    assert state["clusters"]["demo-cluster"]["best_candidate_id"] == "demo-candidate-2"
    assert state["records"]["demo-record-1"]["outcome"] == "FAIL"
    assert LEGACY_NAME not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")

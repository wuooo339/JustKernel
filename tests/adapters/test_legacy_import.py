from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.legacy_import import LegacyImporter, LegacyImportError
from justkernel.platform.persistence.migrations import apply_migrations


def _old_database(path: Path) -> str:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE teams (id TEXT PRIMARY KEY, runtime TEXT, model TEXT, active INTEGER);
        CREATE TABLE members (team TEXT, name TEXT, role TEXT, model TEXT);
        CREATE TABLE runs (id TEXT PRIMARY KEY, team TEXT, model TEXT, state TEXT);
        CREATE TABLE experiences (id TEXT PRIMARY KEY, team TEXT, data TEXT);
        CREATE TABLE events (seq INTEGER PRIMARY KEY, team TEXT, kind TEXT, data TEXT);
        """
    )
    connection.execute("INSERT INTO teams VALUES ('team-1', 'deepagents', 'm1', 1)")
    connection.execute("INSERT INTO members VALUES ('team-1', 'mentor', 'mentor', 'm1')")
    connection.execute("INSERT INTO runs VALUES ('run-1', 'team-1', 'm1', 'completed')")
    connection.execute("INSERT INTO experiences VALUES ('exp-1', 'team-1', '{\"score\": 1}')")
    connection.execute(
        "INSERT INTO events VALUES (1, 'team-1', 'candidate.selected', '{\"id\":\"c1\"}')"
    )
    connection.commit()
    connection.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_database(path: Path) -> sqlite3.Connection:
    connection = connect(str(path))
    apply_migrations(connection)
    return connection


def test_legacy_import_is_read_only_idempotent_and_not_active(tmp_path: Path) -> None:
    old_path = tmp_path / "old.db"
    old_digest = _old_database(old_path)
    connection = _new_database(tmp_path / "journal.db")
    importer = LegacyImporter(connection, old_path)

    first = importer.import_data(now_ms=100)
    second = importer.import_data(now_ms=200)

    assert first.already_imported is False
    assert first.source_digest == old_digest
    assert first.records_imported == 5
    assert second.already_imported is True
    assert second.import_id == first.import_id
    assert hashlib.sha256(old_path.read_bytes()).hexdigest() == old_digest

    count = connection.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0]
    assert count == 5
    assert {row[0] for row in connection.execute("SELECT DISTINCT kind FROM legacy_records")} == {
        "TEAMS",
        "MEMBERS",
        "RUNS",
        "EXPERIENCES",
        "EVENTS",
    }
    assert connection.execute("SELECT COUNT(*) FROM clusters").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM board_posts").fetchone()[0] == 0

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE legacy_records SET payload_json = '{}'")


def test_legacy_import_rejects_missing_source(tmp_path: Path) -> None:
    connection = _new_database(tmp_path / "journal.db")
    with pytest.raises(LegacyImportError):
        LegacyImporter(connection, tmp_path / "missing.db").import_data()

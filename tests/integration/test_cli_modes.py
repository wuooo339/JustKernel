from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from justkernel.bootstrap.cli import main
from justkernel.platform.config import RunMode, apply_cli, load_config
from justkernel.platform.persistence.database import connect


def _old_database(path: Path) -> str:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE teams (id TEXT PRIMARY KEY, runtime TEXT)")
    connection.execute("INSERT INTO teams VALUES ('legacy-team', 'deepagents')")
    connection.commit()
    connection.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_config_precedence_and_immutability(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("JUSTKERNEL_MODE=worker\nJUSTKERNEL_PORT=5000\n")
    env = {
        "JUSTKERNEL_MODE": "demo",
        "JUSTKERNEL_DATA_ROOT": str(tmp_path / "data"),
        "JUSTKERNEL_PORT": "6000",
    }

    config = load_config(env, cwd=tmp_path)
    overridden = apply_cli(config, mode="cluster", port=7000)

    assert config.mode is RunMode.DEMO
    assert config.port == 6000
    assert overridden.mode is RunMode.CLUSTER
    assert overridden.port == 7000
    assert not config.data_root.exists()
    with pytest.raises(FrozenInstanceError):
        config.port = 1  # type: ignore[misc]


def test_cluster_demo_worker_modes(capsys) -> None:
    assert main(["--mode", "cluster", "--data-root", ".data"]) == 0
    cluster = capsys.readouterr().out
    assert "mode=cluster" in cluster
    assert main(["--mode", "worker", "--data-root", ".data"]) == 0
    assert "mode=worker" in capsys.readouterr().out
    assert main(["--mode", "demo", "--data-root", ".data"]) == 0
    assert "mode=demo" in capsys.readouterr().out


def test_invalid_mode_is_rejected_by_cli() -> None:
    with pytest.raises(SystemExit) as error:
        main(["--mode", "invalid"])
    assert error.value.code == 2


def test_migrate_requires_legacy_db(tmp_path: Path, capsys) -> None:
    assert main(["--mode", "migrate", "--data-root", str(tmp_path / "data")]) == 2
    assert "requires --legacy-db" in capsys.readouterr().err


def test_migrate_runs_read_only_legacy_import(tmp_path: Path, capsys) -> None:
    old = tmp_path / "old.db"
    digest = _old_database(old)

    assert (
        main(
            [
                "--mode",
                "migrate",
                "--data-root",
                str(tmp_path / "data"),
                "--legacy-db",
                str(old),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "imported=1" in output
    assert "idempotent=false" in output
    assert hashlib.sha256(old.read_bytes()).hexdigest() == digest
    journal = connect(str(tmp_path / "data" / "journal.db"))
    try:
        count = journal.execute("SELECT COUNT(*) FROM legacy_records").fetchone()[0]
        assert count == 1
    finally:
        journal.close()

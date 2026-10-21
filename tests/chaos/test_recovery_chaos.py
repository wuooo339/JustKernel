from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from justkernel.platform.hardware.ledger import DeviceLease, HardwareLedgerError
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.platform.persistence.recovery import recover


# ---- fixtures ---------------------------------------------------------------
def _journal(tmp_path: Path) -> sqlite3.Connection:
    connection = connect(str(tmp_path / "journal.db"))
    apply_migrations(connection)
    connection.execute(
        """
        INSERT INTO clusters (
            id, operator_id, supervisor_id, operator_spec_digest, start_mode,
            phase, state, max_agents, created_at, version
        ) VALUES ('c1', 'op', 's1', 'spec', 'GENERATE', 'OPTIMIZING',
                  'RUNNING', 100, 0, 0)
        """
    )
    connection.execute(
        """
        INSERT INTO agents (
            id, cluster_id, role, mentor_id, model_profile, skills_json,
            state, created_at, version
        ) VALUES ('a1', 'c1', 'MENTOR', NULL, 'model', '[]', 'RUNNING', 0, 0)
        """
    )
    connection.execute(
        """
        INSERT INTO directions (
            id, cluster_id, mentor_id, objective, constraints_json, state,
            created_at, version
        ) VALUES ('d1', 'c1', 'a1', 'objective', '[]', 'ACTIVE', 0, 0)
        """
    )
    connection.execute(
        """
        INSERT INTO tasks (
            id, cluster_id, mentor_id, worker_id, kind, direction_id,
            operator_spec_digest, context_artifact, context_digest, budget_ref,
            objective, constraints_json, state, created_at, version
        ) VALUES ('t1', 'c1', 'a1', 'a1', 'GENERATE', 'd1', 'spec',
                  'artifact://context', 'context', 'budget', 'objective', '[]',
                  'RUNNING', 0, 0)
        """
    )
    connection.commit()
    return connection


class _MissingLeaseLedger:
    def __init__(self) -> None:
        self.quarantined: list[tuple[str, str]] = []

    def get_lease(self, lease_id: str) -> DeviceLease:
        raise HardwareLedgerError("device disappeared")

    def mark_expired(self, lease_id: str, now_ms: int) -> DeviceLease:
        raise HardwareLedgerError("unknown lease")

    def quarantine(self, device_id: str, reason: str, now_ms: int) -> None:
        self.quarantined.append((device_id, reason))


class _DiskFullConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
        if "UPDATE agents" in sql:
            raise sqlite3.OperationalError("database or disk is full")
        return self._connection.execute(sql, *args)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


# ---- drills -----------------------------------------------------------------
@pytest.mark.skipif(os.name == "nt", reason="SIGKILL drill is POSIX-only")
def test_kill_9_recovery_interrupts_without_replay(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    script = (
        "import sqlite3,sys,time;"
        "db=sqlite3.connect(sys.argv[1]);"
        "db.execute('SELECT 1').fetchone();"
        "time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "journal.db")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
    assert process.returncode == -signal.SIGKILL
    report = recover(journal, now_ms=100)
    assert report.agents_interrupted == 1
    assert report.tasks_interrupted == 1
    assert report.clusters_paused == 1
    assert journal.execute("SELECT state FROM tasks WHERE id='t1'").fetchone()[0] == "INTERRUPTED"
    assert journal.execute("SELECT state FROM clusters WHERE id='c1'").fetchone()[0] == "PAUSED"
    # Recovery must not create a replacement task.
    assert journal.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_missing_device_lease_quarantines_and_expires(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.execute(
        """
        INSERT INTO hardware_leases (
            id, device_id, task_id, owner_agent_id, state, acquired_at,
            expires_at, version
        ) VALUES ('lease-1', 'npu:0', 't1', 'a1', 'LEASED', 0, 50, 0)
        """
    )
    journal.commit()
    ledger = _MissingLeaseLedger()

    report = recover(journal, now_ms=100, ledger=ledger)

    assert report.leases_expired == 1
    assert report.devices_quarantined == 1
    assert ledger.quarantined == [("npu:0", "journal lease missing in global ledger")]
    lease = journal.execute("SELECT state FROM hardware_leases WHERE id='lease-1'").fetchone()
    assert lease[0] == "EXPIRED"


def test_disk_full_rolls_back_recovery(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    failing = _DiskFullConnection(journal)

    with pytest.raises(sqlite3.OperationalError):
        recover(failing, now_ms=100)  # type: ignore[arg-type]

    assert journal.execute("SELECT state FROM agents WHERE id='a1'").fetchone()[0] == "RUNNING"
    assert journal.execute("SELECT state FROM tasks WHERE id='t1'").fetchone()[0] == "RUNNING"
    assert journal.execute("SELECT state FROM clusters WHERE id='c1'").fetchone()[0] == "RUNNING"

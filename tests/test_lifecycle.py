"""Restart recovery may end orphan model work, never release hardware leases."""

import pytest

from aworker.config import Settings
from aworker.lab.lifecycle import recover_model_work, service_lock
from aworker.lab.service import LabService


# ---- process lock and explicit interruption ---------------------------------
def test_service_lock_excludes_second_owner_and_releases_on_exit(tmp_path):
    with (
        service_lock(tmp_path),
        pytest.raises(ValueError, match="another service"),
        service_lock(tmp_path),
    ):
        pass
    with service_lock(tmp_path):
        pass


def test_recovery_retains_checkpoints_and_never_changes_device_work(tmp_path):
    lab = LabService(
        Settings(lab_root=tmp_path, lab_private_root=tmp_path / "private", _env_file=None)
    )
    lab.store.join("fixture", "deepagents", "gpt-api")
    lab.store.join("device-fixture", "deepagents", "gpt-api")
    lab.store.operation("model-op", "fixture", "run")
    lab.store.operation("device-op", "device-fixture", "evaluate")
    lab.store.run_started("run", "fixture", "gpt-api", "thread")
    checkpoint = tmp_path / "checkpoints.sqlite3"
    checkpoint.write_bytes(b"fixture-preserved")
    with service_lock(tmp_path):
        recover_model_work(lab)
    snapshot = lab.store.snapshot()
    states = {o["id"]: o["state"] for o in snapshot["operations"]}
    assert states == {"model-op": "failed", "device-op": "running"}
    assert snapshot["runs"][0]["state"] == "failed"
    assert checkpoint.read_bytes() == b"fixture-preserved"

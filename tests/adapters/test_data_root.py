from __future__ import annotations

import os
from pathlib import Path

import pytest

from justkernel.platform.config import AppConfig, RunMode
from justkernel.platform.data_root import (
    ServiceLock,
    ServiceLockError,
    initialize_data_root,
)


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        mode=RunMode.CLUSTER,
        data_root=tmp_path / "data",
        private_root=tmp_path / "private",
        host="127.0.0.1",
        port=4173,
        log_level="INFO",
    )


def test_initialize_layout_and_permissions(tmp_path: Path) -> None:
    config = _config(tmp_path)
    layout = initialize_data_root(config)
    second = initialize_data_root(config)

    assert layout == second
    assert layout.registry_db.is_file()
    assert layout.hardware_db.is_file()
    assert layout.service_lock.is_file()
    assert layout.clusters_dir.is_dir()
    assert layout.private_dir.is_dir()
    assert not (tmp_path / "data" / "journal.db").exists()
    if os.name != "nt":
        for directory in (
            layout.root,
            layout.clusters_dir,
            layout.root / "private",
            layout.private_dir,
        ):
            assert directory.stat().st_mode & 0o777 == 0o700
        for file in (layout.registry_db, layout.hardware_db, layout.service_lock):
            assert file.stat().st_mode & 0o777 == 0o600


def test_existing_permissions_are_tightened(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not meaningful on Windows")
    config = _config(tmp_path)
    config.data_root.mkdir(mode=0o755)
    config.private_root.mkdir(mode=0o755)

    layout = initialize_data_root(config)

    assert layout.root.stat().st_mode & 0o777 == 0o700
    assert layout.private_dir.stat().st_mode & 0o777 == 0o700


def test_service_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    layout = initialize_data_root(_config(tmp_path))
    first = ServiceLock(layout.service_lock)
    second = ServiceLock(layout.service_lock)

    first.acquire()
    with pytest.raises(ServiceLockError):
        second.acquire()
    first.release()
    second.acquire()
    second.release()

    with ServiceLock(layout.service_lock):
        assert layout.service_lock.read_text(encoding="utf-8").strip()
    with ServiceLock(layout.service_lock):
        pass

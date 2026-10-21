"""Data-root layout, private permissions and single-service locking."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TextIO

from justkernel.platform.config import AppConfig
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError

MODE_DIR = 0o700
MODE_FILE = 0o600


class DataRootError(JustKernelError):
    code = ErrorCode.DATA_ROOT_ERROR


class ServiceLockError(DataRootError):
    pass


@dataclass(frozen=True, slots=True)
class DataRootLayout:
    root: Path
    registry_db: Path
    hardware_db: Path
    clusters_dir: Path
    private_dir: Path
    service_lock: Path


def initialize_data_root(config: AppConfig) -> DataRootLayout:
    root = config.data_root
    clusters = root / "clusters"
    private_under_root = root / "private"
    for directory in (root, clusters, private_under_root, config.private_root):
        _ensure_dir(directory)
    layout = DataRootLayout(
        root=root,
        registry_db=root / "registry.db",
        hardware_db=root / "hardware.db",
        clusters_dir=clusters,
        private_dir=config.private_root,
        service_lock=root / "service.lock",
    )
    for path in (layout.registry_db, layout.hardware_db, layout.service_lock):
        _ensure_file(path)
    return layout


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, MODE_DIR)


def _ensure_file(path: Path) -> None:
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, MODE_FILE)
        os.close(descriptor)
    os.chmod(path, MODE_FILE)


class ServiceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise ServiceLockError("service lock is already held")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            _ensure_file(self.path)
        os.chmod(self.path, MODE_FILE)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            self._lock(handle)
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except OSError as error:
            handle.close()
            raise ServiceLockError("another JustKernel service is already running") from error
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            self._unlock(handle)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> ServiceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

    def _lock(self, handle: TextIO) -> None:
        if os.name == "nt":
            msvcrt = __import__("msvcrt")

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(self, handle: TextIO) -> None:
        if os.name == "nt":
            msvcrt = __import__("msvcrt")

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

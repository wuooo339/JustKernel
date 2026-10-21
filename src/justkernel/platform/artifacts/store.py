"""Content-addressed artifact store."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from justkernel.platform.artifacts.errors import ArtifactCorruptError, ArtifactMissingError
from justkernel.shared.digest import Digest


# ---- ArtifactStore ----------------------------------------------------------
class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ref_for(self, digest: Digest) -> str:
        return f"sha256/{digest.value[:2]}/{digest.value[2:4]}/{digest.value}"

    def path_for(self, digest: Digest) -> Path:
        return self.root / self.ref_for(digest)

    def put_bytes(self, data: bytes) -> Digest:
        digest = Digest.from_bytes(data)
        target = self.path_for(digest)
        if target.exists():
            if self.verify(digest):
                return digest
            raise ArtifactCorruptError(f"existing artifact is corrupt: {digest.value}")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._write_atomic(target, data)
        return digest

    def put_text(self, text: str) -> Digest:
        return self.put_bytes(text.encode("utf-8"))

    def put_file(self, path: Path) -> Digest:
        return self.put_bytes(path.read_bytes())

    def get_bytes(self, digest: Digest) -> bytes:
        path = self.path_for(digest)
        if not path.is_file():
            raise ArtifactMissingError(f"artifact not found: {digest.value}")
        data = path.read_bytes()
        if Digest.from_bytes(data) != digest:
            raise ArtifactCorruptError(f"artifact hash mismatch: {digest.value}")
        return data

    def get_text(self, digest: Digest) -> str:
        return self.get_bytes(digest).decode("utf-8")

    def verify(self, digest: Digest) -> bool:
        try:
            self.get_bytes(digest)
        except (ArtifactMissingError, ArtifactCorruptError, OSError):
            return False
        return True

    def _write_atomic(self, target: Path, data: bytes) -> None:
        descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
            os.chmod(target, 0o600)
            self._fsync_dir(target.parent)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    def _fsync_dir(self, directory: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

import pytest

from justkernel.platform.artifacts.errors import ArtifactCorruptError, ArtifactMissingError
from justkernel.platform.artifacts.store import ArtifactStore
from justkernel.shared.digest import Digest


# ---- helpers ----------------------------------------------------------------
def _store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


# ---- put/get/layout ---------------------------------------------------------
def test_put_get_and_layout(tmp_path: Path) -> None:
    store = _store(tmp_path)
    digest = store.put_bytes(b"hello")

    assert digest.value == sha256(b"hello").hexdigest()
    assert store.get_bytes(digest) == b"hello"
    assert store.get_text(store.put_text("hello")) == "hello"
    assert store.verify(digest)
    assert store.ref_for(digest) == (
        f"sha256/{digest.value[:2]}/{digest.value[2:4]}/{digest.value}"
    )
    assert store.path_for(digest).is_file()


def test_deduplication_keeps_one_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.put_bytes(b"same content")
    path = store.path_for(first)
    inode = path.stat().st_ino

    second = store.put_bytes(b"same content")

    assert first == second
    assert path.stat().st_ino == inode
    assert list(path.parent.glob(".tmp-*")) == []


def test_posix_permissions_are_private(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not meaningful on Windows")

    store = _store(tmp_path)
    digest = store.put_bytes(b"private")
    path = store.path_for(digest)

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_text_and_file_helpers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "input.bin"
    source.write_bytes(b"file content")

    digest = store.put_file(source)

    assert store.get_bytes(digest) == b"file content"
    assert store.get_text(store.put_text("中")) == "中"


# ---- missing/corrupt --------------------------------------------------------
def test_missing_artifact_raises_and_verify_is_false(tmp_path: Path) -> None:
    store = _store(tmp_path)
    missing = Digest.from_text("missing")

    with pytest.raises(ArtifactMissingError):
        store.get_bytes(missing)
    assert store.verify(missing) is False


def test_corrupt_artifact_raises_and_verify_is_false(tmp_path: Path) -> None:
    store = _store(tmp_path)
    digest = store.put_bytes(b"original")
    store.path_for(digest).write_bytes(b"tampered")

    with pytest.raises(ArtifactCorruptError):
        store.get_bytes(digest)
    assert store.verify(digest) is False


def test_existing_corrupt_artifact_is_not_deduped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    digest = store.put_bytes(b"original")
    store.path_for(digest).write_bytes(b"tampered")

    with pytest.raises(ArtifactCorruptError):
        store.put_bytes(b"original")

"""Synthetic sharing errors verify bounded retries; no permissions are changed."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from aworker.lab import persistence


# ---- brief file sharing locks preserve the atomic replacement ---------------
def test_atomic_replace_retries_only_until_the_sharing_lock_clears(tmp_path, monkeypatch):
    source, target = tmp_path / "next.tmp", tmp_path / "record.json"
    source.write_text("new")
    target.write_text("old")
    attempts, delays = [], []
    original = Path.replace

    def replace(path, destination):
        attempts.append(path)
        if len(attempts) <= 2:
            error = PermissionError("explicit sharing fixture")
            error.winerror = 32
            raise error
        return original(path, destination)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(persistence, "time", SimpleNamespace(sleep=delays.append))
    persistence.replace_file(source, target)
    assert len(attempts) == 3 and delays == [0.02, 0.04]
    assert target.read_text() == "new" and not source.exists()


# ---- persistent or unrelated denial is never hidden or granted --------------
@pytest.mark.parametrize("winerror, expected_attempts", [(5, 6), (None, 1)])
def test_atomic_replace_propagates_denial_and_keeps_both_files(
    tmp_path, monkeypatch, winerror, expected_attempts
):
    source, target = tmp_path / "next.tmp", tmp_path / "record.json"
    source.write_text("new")
    target.write_text("old")
    attempts, delays = [], []

    def deny(path, destination):
        attempts.append(path)
        error = PermissionError("explicit persistent denial fixture")
        if winerror is not None:
            error.winerror = winerror
        raise error

    monkeypatch.setattr(Path, "replace", deny)
    monkeypatch.setattr(persistence, "time", SimpleNamespace(sleep=delays.append))
    with pytest.raises(PermissionError):
        persistence.replace_file(source, target)
    assert len(attempts) == expected_attempts and len(delays) == expected_attempts - 1
    assert target.read_text() == "old" and source.read_text() == "new"

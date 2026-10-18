"""Tests for the client-supplied workspace extension."""

import pytest
from a2a.types import Message, Role
from deepagents.backends import FilesystemBackend
from google.protobuf import json_format

from aworker.server.extensions import WORKSPACE_EXTENSION
from aworker.server.workspace import (
    MissingWorkspaceError,
    build_workspace_backend,
    extract_workspace,
)


# ---- helpers ----------------------------------------------------------------
def _message_with_workspace(root: str) -> Message:
    message = Message(role=Role.ROLE_USER)
    json_format.ParseDict({WORKSPACE_EXTENSION: {"root": root}}, message.metadata)
    return message


# ---- extraction -------------------------------------------------------------
def test_extract_workspace_reads_root(tmp_path) -> None:
    message = _message_with_workspace(str(tmp_path))

    workspace = extract_workspace(message)

    assert workspace is not None
    assert workspace.root == tmp_path


def test_extract_workspace_without_metadata_returns_none() -> None:
    assert extract_workspace(Message(role=Role.ROLE_USER)) is None


def test_extract_workspace_rejects_missing_root(tmp_path) -> None:
    message = Message(role=Role.ROLE_USER)
    json_format.ParseDict({WORKSPACE_EXTENSION: {}}, message.metadata)

    with pytest.raises(MissingWorkspaceError):
        extract_workspace(message)


def test_extract_workspace_rejects_non_directory(tmp_path) -> None:
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x")

    with pytest.raises(MissingWorkspaceError):
        extract_workspace(_message_with_workspace(str(file_path)))


# ---- backend ----------------------------------------------------------------
def test_build_workspace_backend_returns_filesystem_backend(tmp_path) -> None:
    workspace = extract_workspace(_message_with_workspace(str(tmp_path)))

    backend = build_workspace_backend(workspace)

    assert isinstance(backend, FilesystemBackend)

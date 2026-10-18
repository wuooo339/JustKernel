"""Client-supplied workspace carried as an A2A extension.

The workspace is a directory the client grants the swarm for the duration of a
request. Agents read and write files through a filesystem backend anchored to
that directory, and path traversal outside it is blocked.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from a2a.types import Message
from deepagents.backends import FilesystemBackend

from aworker.server.extensions import (
    WORKSPACE_EXTENSION,
    ExtensionMetadataError,
    read_extension_entry,
)


# ---- MissingWorkspaceError --------------------------------------------------
class MissingWorkspaceError(ExtensionMetadataError):
    """Raised when a required workspace descriptor is absent or invalid."""


# ---- Workspace --------------------------------------------------------------
@dataclass(frozen=True)
class Workspace:
    """Root directory the swarm is allowed to operate within."""

    root: Path


# ---- extract_workspace ------------------------------------------------------
def extract_workspace(message: Message | None) -> Workspace | None:
    """Read the workspace descriptor from the ``workspace`` metadata, if present."""
    entry = read_extension_entry(message, WORKSPACE_EXTENSION)
    if entry is None:
        return None

    return _parse_workspace(entry)


# ---- build_workspace_backend ------------------------------------------------
def build_workspace_backend(workspace: Workspace) -> FilesystemBackend:
    """Return a filesystem backend confined to the workspace root."""
    return FilesystemBackend(root_dir=workspace.root, virtual_mode=True)


# ---- _parse_workspace -------------------------------------------------------
def _parse_workspace(entry: dict[str, Any]) -> Workspace:
    root = entry.get("root")

    if not isinstance(root, str) or not root:
        raise MissingWorkspaceError("workspace requires a non-empty 'root'")

    path = Path(root)
    if not path.is_dir():
        raise MissingWorkspaceError(f"workspace root is not an existing directory: {root}")

    return Workspace(root=path)

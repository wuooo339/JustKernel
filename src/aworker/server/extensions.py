"""Client-supplied extension metadata carried on A2A messages.

Both the LLM provider credential and the workspace descriptor travel as A2A
extensions. The agent card declares each extension by name; the client attaches
the matching data to the user message metadata under that same name.
"""

from typing import Any

from a2a.types import Message
from google.protobuf import json_format

LLM_PROVIDER_EXTENSION = "llm-provider"
WORKSPACE_EXTENSION = "workspace"


# ---- ExtensionMetadataError -------------------------------------------------
class ExtensionMetadataError(Exception):
    """Raised when extension metadata is missing, malformed, or invalid."""


# ---- read_extension_entry ---------------------------------------------------
def read_extension_entry(message: Message | None, key: str) -> dict[str, Any] | None:
    """Return the metadata object stored under ``key``, or ``None`` if absent."""
    if message is None or not message.HasField("metadata"):
        return None

    metadata = json_format.MessageToDict(message.metadata)
    entry = metadata.get(key)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ExtensionMetadataError(f"extension '{key}' metadata must be an object")
    return entry

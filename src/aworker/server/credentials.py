"""Client-supplied LLM provider credential carried as an A2A extension.

An agent that cannot reach an LLM inference service on its own declares the
``llm-provider`` extension in its agent card. The client then attaches the
endpoint URL and access key to the user message metadata under that name.
"""

from dataclasses import dataclass
from typing import Any

from a2a.types import Message

from aworker.server.extensions import (
    LLM_PROVIDER_EXTENSION,
    ExtensionMetadataError,
    read_extension_entry,
)


# ---- MissingCredentialError -------------------------------------------------
class MissingCredentialError(ExtensionMetadataError):
    """Raised when a required LLM provider credential is absent or invalid."""


# ---- LLMCredential ----------------------------------------------------------
@dataclass(frozen=True)
class LLMCredential:
    """Endpoint and access key for an OpenAI-compatible LLM service."""

    base_url: str
    api_key: str
    model: str | None = None


# ---- extract_llm_credential -------------------------------------------------
def extract_llm_credential(message: Message | None) -> LLMCredential | None:
    """Read the LLM credential from the ``llm-provider`` metadata, if present."""
    entry = read_extension_entry(message, LLM_PROVIDER_EXTENSION)
    if entry is None:
        return None

    return _parse_llm_credential(entry)


# ---- _parse_llm_credential --------------------------------------------------
def _parse_llm_credential(entry: dict[str, Any]) -> LLMCredential:
    base_url = entry.get("base_url")
    api_key = entry.get("api_key")

    if not isinstance(base_url, str) or not base_url:
        raise MissingCredentialError("llm-provider requires a non-empty 'base_url'")
    if not isinstance(api_key, str) or not api_key:
        raise MissingCredentialError("llm-provider requires a non-empty 'api_key'")

    model = entry.get("model")
    if model is not None and not isinstance(model, str):
        raise MissingCredentialError("llm-provider 'model' must be a string")

    return LLMCredential(base_url=base_url, api_key=api_key, model=model)

"""Tests for client-supplied LLM credentials via the A2A extension."""

import asyncio

import pytest
from a2a.types import Message, Role
from google.protobuf import json_format
from starlette.testclient import TestClient

from aworker.config import Settings
from aworker.server.app import create_app
from aworker.server.credentials import MissingCredentialError, extract_llm_credential
from aworker.server.extensions import LLM_PROVIDER_EXTENSION, WORKSPACE_EXTENSION
from aworker.swarm import MemberAgent, Swarm


# ---- helpers ----------------------------------------------------------------
def _message_with_credential(base_url: str, api_key: str) -> Message:
    message = Message(role=Role.ROLE_USER)
    json_format.ParseDict(
        {LLM_PROVIDER_EXTENSION: {"base_url": base_url, "api_key": api_key}},
        message.metadata,
    )
    return message


# ---- extraction -------------------------------------------------------------
def test_extract_llm_credential_reads_extension_metadata() -> None:
    message = _message_with_credential("https://llm.example.com/v1", "sk-123")

    credential = extract_llm_credential(message)

    assert credential is not None
    assert credential.base_url == "https://llm.example.com/v1"
    assert credential.api_key == "sk-123"


def test_extract_llm_credential_without_metadata_returns_none() -> None:
    assert extract_llm_credential(Message(role=Role.ROLE_USER)) is None


def test_extract_llm_credential_rejects_missing_api_key() -> None:
    message = Message(role=Role.ROLE_USER)
    json_format.ParseDict(
        {LLM_PROVIDER_EXTENSION: {"base_url": "https://llm.example.com/v1"}},
        message.metadata,
    )

    with pytest.raises(MissingCredentialError):
        extract_llm_credential(message)


# ---- agent card -------------------------------------------------------------
def test_agent_card_declares_credential_extension() -> None:
    settings = Settings(agent_name="TestSwarm")
    swarm = Swarm(settings)
    swarm.add_member(
        MemberAgent(name="worker", description="d", system_prompt="s", model=settings.model)
    )

    with TestClient(create_app(settings, swarm)) as client:
        card = client.get("/.well-known/agent-card.json").json()

    extensions = card["capabilities"]["extensions"]
    declared = {extension["uri"]: extension for extension in extensions}
    assert declared[LLM_PROVIDER_EXTENSION]["required"] is True
    assert declared[WORKSPACE_EXTENSION].get("required", False) is False


# ---- swarm enforcement ------------------------------------------------------
def test_swarm_requires_credential_when_configured() -> None:
    settings = Settings(require_llm_credential=True)
    swarm = Swarm(settings)

    with pytest.raises(MissingCredentialError):
        asyncio.run(swarm.respond("hi", "thread-1"))


# ---- request flow -----------------------------------------------------------
def test_request_credential_reaches_swarm(tmp_path) -> None:
    settings = Settings()
    swarm = Swarm(settings)
    swarm.add_member(
        MemberAgent(name="worker", description="d", system_prompt="s", model=settings.model)
    )

    captured: dict[str, object] = {}

    async def fake_respond(prompt, thread_id, credential=None, workspace=None):
        captured["prompt"] = prompt
        captured["credential"] = credential
        captured["workspace"] = workspace
        return "reply-ok"

    swarm.respond = fake_respond

    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "m1",
                "role": "ROLE_USER",
                "parts": [{"text": "hello"}],
                "metadata": {
                    LLM_PROVIDER_EXTENSION: {
                        "base_url": "https://llm.example.com/v1",
                        "api_key": "sk-123",
                    },
                    WORKSPACE_EXTENSION: {"root": str(tmp_path)},
                },
            }
        },
    }

    with TestClient(create_app(settings, swarm)) as client:
        response = client.post("/", json=body, headers={"A2A-Version": "1.0"})

    result = response.json()["result"]["message"]
    assert result["parts"][0]["text"] == "reply-ok"
    assert captured["prompt"] == "hello"
    assert captured["credential"].api_key == "sk-123"
    assert captured["workspace"].root == tmp_path

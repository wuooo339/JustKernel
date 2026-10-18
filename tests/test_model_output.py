"""Verify output policy in serialized SDK requests without calling a model service."""

import json

import httpx
import pytest
from langchain_core.messages import HumanMessage
from pydantic import SecretStr

from aworker.config import Settings
from aworker.lab.providers import ModelProfile, ModelRegistry


# ---- API output policy at the HTTP boundary --------------------------------
@pytest.mark.parametrize("provider", ["openai", "glm", "deepseek", "qwen", "compatible"])
@pytest.mark.parametrize("limit", [None, 131072])
def test_output_limit_is_omitted_unless_explicitly_requested(provider, limit):
    registry = ModelRegistry(
        Settings(lab_provider_keys={"fixture": SecretStr("fixture-key")}, _env_file=None)
    )
    registry.profiles["fixture"] = ModelProfile(
        name="Fixture",
        provider=provider,
        model="fixture-model",
        base_url="https://fixture.invalid/v1",
        max_tokens=limit,
        streaming=False,
    )
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "fixture-response",
                "object": "chat.completion",
                "created": 0,
                "model": "fixture-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "fixture answer"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    model = registry.build("fixture")
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        model.root_client = model.root_client.with_options(http_client=transport)
        model.client = model.root_client.chat.completions
        assert model.invoke([HumanMessage("fixture task")]).content == "fixture answer"
    assert len(requests) == 1
    token_fields = {
        key: value
        for key, value in requests[0].items()
        if key in {"max_tokens", "max_completion_tokens", "max_output_tokens"}
    }
    expected_key = "max_completion_tokens" if provider == "openai" else "max_tokens"
    assert token_fields == ({} if limit is None else {expected_key: limit})

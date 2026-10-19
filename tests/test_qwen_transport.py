"""Qwen streaming tool round trip against a local HTTP fixture, not a paid API."""

import json

import httpx
from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import SecretStr

from aworker.config import Settings
from aworker.lab.providers import ModelRegistry


# ---- real SDK serialization, incremental tools/reasoning, usage and resumption ----
def test_qwen_flash_streaming_tool_history_and_unlimited_default_output():
    registry = ModelRegistry(
        Settings(lab_provider_keys={"qwen": SecretStr("fixture")}, _env_file=None)
    )
    model = registry.build("qwen-api")
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert (
            str(request.url) == "https://maas.qianwenaiapi.com/compatible-mode/v1/chat/completions"
        )
        deltas = (
            [
                {"role": "assistant", "reasoning_content": "fixture "},
                {"reasoning_content": "reasoning"},
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-fixture",
                            "type": "function",
                            "function": {"name": "read_spec", "arguments": "{}"},
                        }
                    ]
                },
            ]
            if len(requests) == 1
            else [{"role": "assistant", "content": "OK"}]
        )
        chunks = [
            {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "qwen3.8-flash",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }
            for delta in deltas
        ]
        chunks.append(
            {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "qwen3.8-flash",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                    }
                ],
            }
        )
        chunks.append(
            {
                "id": "fixture",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "qwen3.8-flash",
                "choices": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            }
        )
        stream = (
            "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=stream)

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        model.root_client = model.root_client.with_options(http_client=transport)
        model.client = model.root_client.chat.completions
        prompt = HumanMessage("fixture task")
        first = model.invoke([prompt])
        assert first.tool_calls[0]["name"] == "read_spec"
        assert first.additional_kwargs["reasoning_content"] == "fixture reasoning"
        assert first.usage_metadata["total_tokens"] == 13
        assert "fixture reasoning" not in str(first.content)
        second = model.invoke(
            [prompt, first, ToolMessage("fixture specification", tool_call_id="call-fixture")]
        )
        assert second.content == "OK"
    for request in requests:
        assert request["model"] == "qwen3.8-flash"
        assert request["reasoning_effort"] == "low"
        assert request["enable_thinking"] and request["preserve_thinking"]
        assert "max_tokens" not in request and "max_completion_tokens" not in request
        assert request["stream"] and request["stream_options"]["include_usage"]
    assert requests[1]["messages"][1]["reasoning_content"] == "fixture reasoning"

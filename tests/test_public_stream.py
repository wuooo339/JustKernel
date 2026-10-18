"""Public synthetic chunks verify observability without exposing private reasoning."""

import json

from langchain_core.messages import AIMessage, AIMessageChunk
from test_judge_automation import lab as lab

from aworker.lab.deepagent import DeepAgentRuntime


# ---- text/tool deltas arrive before completion; private fields are ignored ---
def test_public_text_and_tool_arguments_stream_without_private_reasoning(lab):
    runtime = DeepAgentRuntime(lab, "gpt-001", "fixture-run")
    runtime.observable({"event": "on_chat_model_start", "run_id": "fixture-call"})
    runtime.observable(
        {
            "event": "on_chat_model_stream",
            "run_id": "fixture-call",
            "data": {
                "chunk": AIMessageChunk(
                    content=[
                        {"type": "reasoning", "text": "PRIVATE"},
                        {"type": "text", "text": "修改通用归约。"},
                    ],
                    additional_kwargs={"reasoning_content": "PRIVATE"},
                    tool_call_chunks=[
                        {
                            "index": 0,
                            "name": "edit_file",
                            "args": '{"file_path":"/project/kernel.h"',
                        }
                    ],
                )
            },
        }
    )
    before = lab.store.events()
    delta = next(e for e in before if e["kind"] == "model.output.delta")
    assert delta["data"]["text"] == "修改通用归约。"
    assert delta["data"]["tools"][0]["name"] == "edit_file"
    assert not any(e["kind"] == "model.completed" for e in before)
    runtime.observable(
        {
            "event": "on_chat_model_end",
            "run_id": "fixture-call",
            "data": {
                "output": AIMessage(
                    "公开结论",
                    usage_metadata={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12},
                )
            },
        }
    )
    events = lab.store.events()
    assert "PRIVATE" not in json.dumps(events)
    done = next(e for e in events if e["kind"] == "model.completed")
    assert done["data"]["usage"]["total_tokens"] == 12
    assert done["data"]["model_call_id"] == "fixture-call"


# ---- batching retains ordered public text without a database write per token -
def test_public_stream_batches_and_flushes_remaining_text_at_completion(lab, monkeypatch):
    monkeypatch.setattr("aworker.lab.deepagent.time.monotonic", lambda: 1)
    runtime = DeepAgentRuntime(lab, "gpt-001", "fixture-run")
    for text in ["a", "b", "c", "d"]:
        runtime.observable(
            {
                "event": "on_chat_model_stream",
                "run_id": "fixture-call",
                "data": {"chunk": AIMessageChunk(content=text)},
            }
        )
    assert sum(e["kind"] == "model.output.delta" for e in lab.store.events()) == 1
    runtime.observable(
        {
            "event": "on_chat_model_end",
            "run_id": "fixture-call",
            "data": {"output": AIMessage("abcd")},
        }
    )
    deltas = [e["data"]["text"] for e in lab.store.events() if e["kind"] == "model.output.delta"]
    assert deltas == ["a", "bcd"]

"""Bounded public model/tool events for the independent, read-only Judger."""

import json
import time
from uuid import uuid4

from aworker.lab.deepagent import text_content


# ---- public Judger session; never serialize provider internals ---------------
class JudgeSession:
    def __init__(self, service, profile):
        self.service = service
        self.run = "judge-" + uuid4().hex
        self.profile = profile
        self.calls = {}
        self.last_call = None

    def emit(self, kind, **data):
        self.service.store.event("controller", kind, run_id=self.run, agent="judger", **data)

    def start(self):
        self.emit("control.started", operation_id=self.run, action="judger", model=self.profile)

    def finish(
        self, state="completed", message="独立源码复核结束；官测提交与回执由执行服务继续处理。"
    ):
        self.emit("control." + state, operation_id=self.run, message=message)

    # ---- only public content and tool arguments, batched for live transport --
    def flush(self, key):
        item = self.calls[key]
        if item["text"] or item["tools"]:
            self.emit(
                "model.output.delta",
                model_call_id=key,
                text=self.service.redact(item["text"]),
                tools=[{"index": i, **v} for i, v in item["tools"].items()],
                display_truncated=item["seen"] >= 64000,
            )
            item.update(text="", tools={}, last=time.monotonic())

    def observe(self, event):
        kind, data = event["event"], event.get("data", {})
        key = str(event.get("run_id", "unknown"))
        if kind == "on_chat_model_start":
            self.last_call = key
            self.calls[key] = {
                "start": time.monotonic(),
                "text": "",
                "tools": {},
                "seen": 0,
                "last": 0,
            }
            model = next(
                (m for m in self.service.registry.catalog() if m["id"] == self.profile), {}
            )
            self.emit("model.started", model_call_id=key, model=model.get("model", self.profile))
        elif kind == "on_chat_model_stream" and key in self.calls:
            item, chunk = self.calls[key], data.get("chunk")
            text = text_content(getattr(chunk, "content", ""))[: max(0, 64000 - item["seen"])]
            item["text"] += text
            item["seen"] += len(text)
            for part in getattr(chunk, "tool_call_chunks", []) or []:
                tool = item["tools"].setdefault(part.get("index", 0), {"name": "", "args": ""})
                tool["name"] += str(part.get("name") or "")[:100]
                args = str(part.get("args") or "")[: max(0, 64000 - item["seen"])]
                tool["args"] += self.service.redact(args)
                item["seen"] += len(args)
            if time.monotonic() - item["last"] >= 0.5:
                self.flush(key)
        elif kind == "on_chat_model_end":
            if key in self.calls:
                self.flush(key)
            output = data.get("output")
            text = text_content(getattr(output, "content", ""))
            if text:
                self.emit(
                    "agent.message",
                    model_call_id=key,
                    text=self.service.redact(text[:16000]),
                    truncated=len(text) > 16000,
                )
            self.emit(
                "model.completed",
                model_call_id=key,
                duration_ms=(time.monotonic() - self.calls[key]["start"]) * 1000
                if key in self.calls
                else None,
                usage=getattr(output, "usage_metadata", None) or {},
            )
        elif kind in {"on_tool_start", "on_tool_end", "on_tool_error"}:
            payload = {"tool": event.get("name"), "tool_call": key, "model_call_id": self.last_call}
            if kind == "on_tool_start":
                payload["input"] = self.service.redact(
                    json.dumps(data.get("input", {}), ensure_ascii=False, default=str)[:16000]
                )
            else:
                raw = data.get("output", data.get("error", ""))
                text = text_content(raw.content) if hasattr(raw, "content") else str(raw)
                payload.update(
                    output=self.service.redact(text[:16000]), truncated=len(text) > 16000
                )
            self.emit(
                {
                    "on_tool_start": "tool.started",
                    "on_tool_end": "tool.completed",
                    "on_tool_error": "tool.failed",
                }[kind],
                **payload,
            )

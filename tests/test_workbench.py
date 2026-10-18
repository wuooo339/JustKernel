"""Workbench boundaries. Test measurements, keys and setup reports are fixtures."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import SecretStr, ValidationError
from starlette.testclient import TestClient

from aworker.config import Settings
from aworker.lab.api import create_lab_app
from aworker.lab.model_settings import APIModelSave, save_api_model
from aworker.lab.operators import OperatorDraft
from aworker.lab.servers import ServerProfile, ServerSave, parse_ssh_text
from aworker.lab.service import LabService
from aworker.lab.setup_agent import ImageInput, SetupJobs, SetupRequest


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture
def workbench(tmp_path):
    service = LabService(
        Settings(
            lab_root=tmp_path / "lab",
            lab_default_operator="RotaryPosEmb",
            lab_execution_mode="hybrid",
            lab_private_root=tmp_path / "private",
            lab_ssh_host=None,
            _env_file=None,
        )
    )
    service.join("team-a", model="gpt-chatgpt")
    return service


# ---- ScriptedSetupModel -----------------------------------------------------
class ScriptedSetupModel(BaseChatModel):
    responses: list[AIMessage]
    image_seen: bool = False

    # ---- model protocol -----------------------------------------------------
    @property
    def _llm_type(self):
        return "fixture-setup-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.image_seen |= any(
            isinstance(m.content, list)
            and any(isinstance(b, dict) and b.get("type") == "image_url" for b in m.content)
            for m in messages
        )
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


# ---- encrypted connection and API settings ---------------------------------
def test_passwords_are_encrypted_and_never_returned_by_local_api(workbench):
    with TestClient(create_lab_app(workbench)) as client:
        profile = ServerProfile(id="fixture", name="Fixture", host="localhost", auth="password")
        r = client.post(
            "/api/lab/workspace/servers",
            json={"profile": profile.model_dump(), "password": "fixture-password"},
        )
        assert r.status_code == 200
        assert "fixture-password" not in workbench.servers.path.read_text()
        status = client.get("/api/lab/workspace/status").json()
        assert status["servers"]["profiles"][0]["has_password"]
        assert "fixture-password" not in json.dumps(status)
        assert workbench.servers.secret("fixture", "password") == "fixture-password"
        invalid = client.post(
            "/api/lab/workspace/servers",
            json={"profile": {**profile.model_dump(), "port": 0}, "password": "fixture-password"},
        )
        assert invalid.status_code == 422
        assert "fixture-password" not in invalid.text
        assert (
            client.post(
                "/api/lab/workspace/servers/fixture/probe",
                json={},
                headers={"Origin": "https://foreign.example"},
            ).status_code
            == 403
        )


def test_saved_api_connection_is_used_by_the_unified_model_registry(workbench):
    request = APIModelSave(
        id="fixture-qwen",
        name="Fixture Qwen",
        provider="qwen",
        model="fixture-model",
        base_url="https://provider.example/v1",
        api_key=SecretStr("fixture-api-key"),
        max_tokens=8192,
    )
    save_api_model(workbench, request)
    stored = (workbench.servers.folder / "models.json").read_text()
    assert "fixture-api-key" not in stored
    assert "fixture-api-key" not in json.dumps(workbench.registry.catalog())
    client = workbench.registry.build("fixture-qwen")
    assert client.model_name == "fixture-model"
    assert client.openai_api_key.get_secret_value() == "fixture-api-key"
    assert client.streaming is False
    assert workbench.redact("error fixture-api-key") == "error [redacted]"
    reloaded = LabService(workbench.settings.model_copy(update={"lab_root": workbench.base_root}))
    assert reloaded.registry.local_keys["fixture-qwen"].get_secret_value() == "fixture-api-key"
    with TestClient(create_lab_app(reloaded)) as api:
        response = api.post(
            "/api/lab/workspace/models",
            json=request.model_dump(mode="json", exclude={"api_key"}) | {"max_tokens": None},
        )
        assert response.status_code == 200
        profile = next(m for m in response.json()["models"] if m["id"] == request.id)
        assert profile["max_tokens"] is None
    restored = LabService(workbench.settings.model_copy(update={"lab_root": workbench.base_root}))
    assert restored.registry.profiles[request.id].max_tokens is None
    assert restored.registry.build(request.id).max_tokens is None
    assert restored.registry.local_keys[request.id].get_secret_value() == "fixture-api-key"
    with pytest.raises(ValidationError, match="supported tools"):
        APIModelSave(
            id="plan",
            name="Plan",
            provider="glm",
            model="fixture",
            base_url="https://open.bigmodel.cn/api/coding/paas/v4",
        )


def test_ssh_parser_and_server_selection_preserve_history_and_exclude_busy_switches(workbench):
    assert parse_ssh_text("ssh -p 2222 developer@example.com") == {
        "port": 2222,
        "user": "developer",
        "host": "example.com",
    }
    assert (
        parse_ssh_text("Host fixture\n HostName 127.0.0.1\n User tester\n Port 2222")["port"]
        == 2222
    )
    with pytest.raises(ValueError):
        parse_ssh_text("ssh example.com rm -rf /tmp/test")
    p = ServerProfile(id="second", name="Second", host="localhost", devices=[0, 1])
    workbench.servers.save(ServerSave(profile=p))
    workbench.store.operation("busy", "team-a", "run")
    with pytest.raises(ValueError, match="finish running"):
        workbench.select_server("second")
    workbench.store.operation_finished("busy", "completed")
    workbench.select_server("second")
    assert {d["device"] for d in workbench.store.snapshot()["devices"]} == {0, 1}
    assert workbench.store.snapshot()["operations"][0]["id"] == "busy"


# ---- independent operator packages -----------------------------------------
def test_operator_creation_inherits_constraints_and_isolates_code_cases_and_journal(workbench):
    default_root = workbench.root
    workbench.store.event("team-a", "fixture.history", message="default only")
    draft = OperatorDraft(
        id="VectorAdd",
        name="Vector Add",
        description="Elementwise x+y.",
        cases=[{"shape": [17], "dtype": "float32", "inputs": ["x", "y"]}],
        constraints="No cross-call caching.",
    )
    result = workbench.catalog.create(draft)
    assert not result["adapter_ready"]
    workbench.select_operator("VectorAdd")
    assert workbench.root != default_root
    assert workbench.operator == "VectorAdd"
    assert len(json.loads((workbench.root / "challenge/cases.json").read_text())) == 1
    constraints = (workbench.root / "challenge/CONSTRAINTS.md").read_text(encoding="utf-8")
    inherited = (default_root / "challenge/CONSTRAINTS.md").read_text(encoding="utf-8")
    assert "Host" in inherited
    assert constraints.startswith("# 算子开发通用约束")
    assert "No cross-call caching." in constraints
    assert not any(e["kind"] == "fixture.history" for e in workbench.store.events())
    workbench.runner = SimpleNamespace(evaluate=lambda *args: pytest.fail("wrong evaluator used"))
    with pytest.raises(ValueError, match="own completed and reviewed evaluator"):
        asyncio.run(workbench.evaluate("team-a"))
    assert not workbench.store.snapshot()["jobs"]
    workbench.select_operator("RotaryPosEmb")
    assert workbench.root == default_root
    assert any(e["kind"] == "fixture.history" for e in workbench.store.events())
    with pytest.raises(ValidationError):
        OperatorDraft(id="../outside", name="Invalid", description="Invalid")


# ---- actual Deep Agents graph, explicit model fixture ------------------------
def test_configuration_assistant_receives_images_and_submits_a_reviewable_draft(
    workbench, monkeypatch
):
    draft = {
        "id": "ImageOp",
        "name": "Image operator",
        "description": "Fixture semantics",
        "cases": [{"shape": [8], "dtype": "float32"}],
        "adapter_reviewed": True,
    }
    model = ScriptedSetupModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "draft-call", "name": "submit_operator_draft", "args": {"draft": draft}}
                ],
            ),
            AIMessage(content="草稿已整理，评测器尚未就绪。"),
        ]
    )
    monkeypatch.setattr(workbench.registry, "build", lambda key: model)
    image = ImageInput(name="fixture.png", data_url="data:image/png;base64,iVBORw0KGgo=")
    jobs = SetupJobs(workbench)

    async def run():
        key = jobs.start(
            SetupRequest(
                kind="operator", model="gpt-chatgpt", prompt="Read fixture image.", images=[image]
            )
        )
        await jobs.tasks[key]
        return jobs.get(key)

    row = asyncio.run(run())
    assert row["state"] == "completed", row
    assert model.image_seen
    assert row["result"]["draft"]["adapter_reviewed"] is False
    assert not any(op["id"] == "ImageOp" for op in workbench.catalog.catalog())
    assert any(
        s["tool"] == "submit_operator_draft" and s["state"] == "completed" for s in row["steps"]
    )


def test_server_assistant_only_saves_a_path_it_actually_detected(workbench, monkeypatch):
    p = ServerProfile(id="fixture", name="Fixture", host="localhost")
    workbench.servers.save(ServerSave(profile=p))
    monkeypatch.setattr(
        "aworker.lab.setup_agent.probe_server",
        lambda *args: {
            "connected": True,
            "cann_env_candidates": ["/fixture/set_env.sh"],
            "devices": "fixture NPU 0",
            "device_indices": [0],
        },
    )
    model = ScriptedSetupModel(
        responses=[
            AIMessage(
                content="", tool_calls=[{"id": "inspect", "name": "inspect_server", "args": {}}]
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "configure",
                        "name": "configure_detected_runtime",
                        "args": {
                            "cann_env": "/fixture/set_env.sh",
                            "remote_root": "/fixture/jobs",
                            "devices": [0],
                        },
                    }
                ],
            ),
            AIMessage(content="检测配置已保存。"),
        ]
    )
    monkeypatch.setattr(workbench.registry, "build", lambda key: model)
    jobs = SetupJobs(workbench)

    async def run():
        key = jobs.start(
            SetupRequest(
                kind="server", model="gpt-chatgpt", prompt="Inspect fixture.", server="fixture"
            )
        )
        await jobs.tasks[key]
        return jobs.get(key)

    row = asyncio.run(run())
    assert row["state"] == "completed", row
    assert workbench.servers.get("fixture").cann_env == "/fixture/set_env.sh"
    assert not workbench.store.snapshot()["jobs"]

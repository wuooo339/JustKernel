"""Unified execution contracts; all measurements here are explicit test fixtures."""

import asyncio
import base64
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import SecretStr
from starlette.testclient import TestClient

from aworker.config import Settings
from aworker.lab.api import create_lab_app
from aworker.lab.bridge import TeamSwarm
from aworker.lab.deepagent import DeepAgentRuntime, text_content
from aworker.lab.domain import Experience, Specialist
from aworker.lab.export import execution_record
from aworker.lab.filesystem import UTF8FilesystemBackend
from aworker.lab.policy import inspect_source
from aworker.lab.providers import ModelRegistry, ReadOnlyChatGPTLogin
from aworker.lab.service import LabService
from aworker.lab.store import LabStore
from aworker.lab.tools import EngineeringTools


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture
def service(tmp_path):
    result = LabService(
        Settings(
            lab_root=tmp_path / "lab",
            lab_default_operator="RotaryPosEmb",
            lab_execution_mode="hybrid",
            lab_ssh_host=None,
            _env_file=None,
        )
    )
    result.join("team-a", model="gpt-chatgpt")
    return result


# ---- ScriptedModel ----------------------------------------------------------
class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]

    # ---- model protocol -----------------------------------------------------
    @property
    def _llm_type(self):
        return "test-scripted-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


# ---- wait_operation ---------------------------------------------------------
def wait_operation(client, state):
    for _ in range(100):
        rows = client.get("/api/lab/snapshot").json()["operations"]
        if rows and rows[-1]["state"] == state:
            return rows[-1]
        time.sleep(0.01)
    pytest.fail("operation did not finish")


# ---- workspace, input identity and registration -----------------------------
def test_only_one_operator_and_clean_independent_workspace(service):
    folder = service.team_folder("team-a")
    assert not (folder / "team.json").exists()
    assert not (folder / "client.py").exists()
    assert len(json.loads((folder / "cases.json").read_text())) == 15
    assert (folder / "skills/kernel-engineering/SKILL.md").is_file()
    assert inspect_source((folder / "kernel.asc").read_text()).automated_pass
    with pytest.raises(ValueError, match="unified"):
        service.join("old-native", "codex", "gpt-chatgpt")
    with pytest.raises(ValueError):
        service.join("../outside", model="gpt-chatgpt")


def test_roster_can_change_only_between_tasks(service):
    service.set_members("team-a", [Specialist(name="review", role="reviewer", model="deepseek")])
    assert service.store.snapshot()["members"][0]["model"] == "deepseek"
    service.store.operation("active", "team-a", "run")
    with pytest.raises(ValueError, match="active"):
        service.set_members("team-a", [Specialist(name="engineer", role="implementer")])


def test_publish_and_learning_are_bound_to_source_and_input_pack(service):
    with pytest.raises(ValueError, match="passing"):
        service.publish("team-a")
    folder = service.team_folder("team-a")
    digest = hashlib.sha256((folder / "kernel.asc").read_bytes()).hexdigest()
    pack = service.root / "challenge/cases.json"
    case_digest = hashlib.sha256(pack.read_bytes()).hexdigest()
    service.store.event(
        "team-a",
        "evaluation.completed",
        source_sha256=digest,
        case_pack_sha256=case_digest,
        job_id="test-evidence",
        cases=[],
        **{"pass": True},
    )
    published = service.publish("team-a")
    assert service.public_code(published["artifact_id"]) == (folder / "kernel.asc").read_text()
    experience = Experience(
        title="test fixture",
        conditions="test only",
        action="no optimization",
        limitations="not a measured improvement",
        evidence_job="test-evidence",
    )
    service.record_experience("team-a", "test-run", experience)
    assert service.store.experiences()[0]["data"]["verified"] == "local-correctness"
    pack.write_text("[]")
    with pytest.raises(ValueError, match="input pack"):
        service.publish("team-a")
    with pytest.raises(ValueError, match="input pack"):
        service.record_experience("team-a", "test-run", experience)


# ---- concurrency and physical leases ----------------------------------------
def test_atomic_device_claim_and_foreign_lease_rejected(tmp_path):
    store = LabStore(tmp_path / "journal.sqlite3")
    store.register_device("one", "server", 0)
    jobs = [store.enqueue("team-" + str(i)) for i in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        leases = list(pool.map(store.claim, jobs))
    assert sum(item is not None for item in leases) == 1
    first = next(i for i, item in enumerate(leases) if item)
    with pytest.raises(ValueError, match="foreign"):
        store.finish(jobs[first], "foreign-token")
    store.finish(jobs[first], leases[first]["token"])
    assert store.claim(jobs[1]) is not None


def test_at_most_eight_teams_and_one_lease_per_team(tmp_path):
    store = LabStore(tmp_path / "journal.sqlite3")
    for i in range(10):
        store.register_device("npu-" + str(i), "server", i)
    jobs = [store.enqueue("team-" + str(i)) for i in range(9)]
    assert all(store.claim(job, max_active=8) for job in jobs[:8])
    assert store.claim(jobs[8], max_active=8) is None
    same_team = store.enqueue("team-0")
    assert store.claim(same_team, max_active=10) is None


def test_cancelling_model_does_not_release_inflight_device_work(service):
    import threading

    started, release = threading.Event(), threading.Event()

    class Runner:
        def evaluate(self, *args):
            started.set()
            assert release.wait(5)
            return {"pass": True}

    service.runner = Runner()

    async def scenario():
        task = asyncio.create_task(service.evaluate("team-a"))
        await asyncio.to_thread(started.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service._evaluations
        release.set()
        await service.close()
        assert not service._evaluations

    asyncio.run(scenario())


# ---- model providers and authentication -------------------------------------
def test_chatgpt_auth_is_read_only_and_expiry_is_explicit(tmp_path):
    path = tmp_path / "auth.json"
    payload = base64.urlsafe_b64encode(json.dumps({"exp": time.time() + 3600}).encode()).decode()
    original = json.dumps(
        {
            "tokens": {
                "access_token": "header." + payload + ".signature",
                "refresh_token": "test-refresh",
                "account_id": "test",
            }
        }
    )
    path.write_text(original)
    assert ReadOnlyChatGPTLogin(path).get_token().expires_at > datetime.now(UTC)
    assert path.read_text() == original
    expired = base64.urlsafe_b64encode(json.dumps({"exp": 1}).encode()).decode()
    path.write_text(original.replace(payload, expired))
    with pytest.raises(ValueError, match="expired"):
        ReadOnlyChatGPTLogin(path).get_token()


def test_provider_metadata_never_exports_credentials(tmp_path):
    secret = "unit-test-private-key"
    registry = ModelRegistry(
        Settings(lab_provider_keys={"openai": SecretStr(secret)}, _env_file=None)
    )
    assert secret not in json.dumps(registry.catalog())
    assert registry.build("gpt-api").model_name == registry.profiles["gpt-api"].model
    with pytest.raises(ValueError, match="not configured"):
        registry.build("deepseek")


def test_deepseek_preserves_reasoning_across_plain_and_tool_turns():
    registry = ModelRegistry(
        Settings(lab_provider_keys={"deepseek": SecretStr("test-only")}, _env_file=None)
    )
    model = registry.build("deepseek")
    messages = [
        HumanMessage("task"),
        AIMessage("answer", additional_kwargs={"reasoning_content": "r1"}),
        HumanMessage("continue"),
        AIMessage(
            "",
            additional_kwargs={"reasoning_content": "r2"},
            tool_calls=[{"name": "ls", "args": {}, "id": "one", "type": "tool_call"}],
        ),
        ToolMessage("ok", tool_call_id="one"),
    ]
    payload = model._get_request_payload(messages)
    assert payload["messages"][1]["reasoning_content"] == "r1"
    assert payload["messages"][3]["reasoning_content"] == "r2"
    assert payload["reasoning_effort"] == "high"
    assert model.extra_body["thinking"]["type"] == "enabled"


# ---- real Deep Agents graph with deterministic local model ------------------
def test_deepagents_tools_checkpoints_and_permissions(service, monkeypatch):
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "read",
                        "name": "read_file",
                        "args": {"file_path": "/skills/kernel-engineering/SKILL.md"},
                    },
                    {
                        "id": "write",
                        "name": "write_file",
                        "args": {"file_path": "/cases.json", "content": "tampered"},
                    },
                ],
            ),
            AIMessage("verified test graph"),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    before = (service.team_folder("team-a") / "cases.json").read_bytes()
    answer = asyncio.run(service.run_team("team-a", "Read skill and test input protection"))
    assert answer == "verified test graph"
    assert (service.team_folder("team-a") / "cases.json").read_bytes() == before
    events = service.store.events()
    assert any(e["kind"] == "skill.loaded" for e in events)
    assert any(e["kind"] == "tool.completed" and e["data"]["tool"] == "read_file" for e in events)
    assert service.store.snapshot()["runs"][0]["state"] == "completed"
    assert (service.root / "checkpoints/team-a.sqlite3").is_file()


def test_missing_analysis_script_is_repairable_in_the_same_graph(service, monkeypatch):
    model = ScriptedModel(
        responses=[
            AIMessage(
                "",
                tool_calls=[
                    {"id": "missing", "name": "run_python", "args": {"script_path": "analysis.py"}}
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "create",
                        "name": "write_file",
                        "args": {
                            "file_path": "/analysis.py",
                            "content": "print('fixture-analysis')\n",
                        },
                    }
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {"id": "retry", "name": "run_python", "args": {"script_path": "analysis.py"}}
                ],
            ),
            AIMessage("analysis recovered"),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    assert (
        asyncio.run(service.run_team("team-a", "Repair missing analysis script"))
        == "analysis recovered"
    )
    events = service.store.events()
    assert any(e["kind"] == "tool.recoverable_error" for e in events)
    assert any(
        e["kind"] == "tool.completed" and "fixture-analysis" in e["data"].get("output", "")
        for e in events
    )
    assert service.store.snapshot()["runs"][0]["state"] == "completed"


def test_reasoning_blocks_are_not_projected_into_public_events(service):
    assert (
        text_content([{"type": "reasoning", "text": "private"}, {"type": "text", "text": "answer"}])
        == "answer"
    )
    runtime = DeepAgentRuntime(service, "team-a", "test-run")
    runtime.observable(
        {
            "event": "on_chat_model_end",
            "name": "test",
            "data": {
                "output": AIMessage("visible", additional_kwargs={"reasoning_content": "private"})
            },
        }
    )
    assert "private" not in json.dumps(service.store.events())


def test_langsmith_configuration_failure_finishes_run(service):
    service.settings.lab_langsmith_enabled = True
    with pytest.raises(ValueError, match="API key"):
        asyncio.run(service.run_team("team-a", "test"))
    assert service.store.snapshot()["runs"][0]["state"] == "failed"


def test_readonly_specialists_have_no_device_or_python_tool(service):
    tools = EngineeringTools(service, "team-a", "run", service.team_folder("team-a"))
    assert not {"run_python", "evaluate_kernel", "publish_result"} & {
        t.name for t in tools.build(True)
    }


# ---- dashboard API and A2A --------------------------------------------------
def test_dashboard_is_integrated_and_provider_configuration_is_typed(service):
    with TestClient(create_lab_app(service)) as client:
        assert 'id="attemptChart"' in client.get("/").text
        assert client.get("/visualization.js").status_code == 200
        assert client.get("/visualization.css").status_code == 200
        assert client.get("/api/lab/health").json()["generation"] == "deepagents-v2"
        bootstrap = client.get("/api/lab/events/bootstrap")
        assert bootstrap.headers["cache-control"] == "no-store"
        assert bootstrap.json()["cursor"] == max(e["seq"] for e in service.store.events())
        card = client.get("/.well-known/agent-card.json").json()
        assert card["supportedInterfaces"][0]["url"].endswith("/a2a/")
        assert not card["capabilities"].get("extensions")
        client.post("/api/lab/control/teams", json={"team": "team-b", "model": "deepseek"})
        assert len(client.get("/a2a/.well-known/agent-card.json").json()["skills"]) == 2
        assert (
            client.post(
                "/api/lab/control/teams",
                json={"team": "legacy", "runtime": "codex", "model": "gpt-api"},
            ).status_code
            == 422
        )
        assert client.get("/api/lab/export").json()["schema"] == "justkernel.events.v2"


def test_cross_site_cannot_start_tasks_and_no_npu_creates_no_fake_job(service):
    with TestClient(create_lab_app(service)) as client:
        assert (
            client.post(
                "/api/lab/control/run",
                json={"team": "team-a", "prompt": "test"},
                headers={"Origin": "https://other.example"},
            ).status_code
            == 403
        )
        assert client.post("/api/lab/control/evaluate", json={"team": "team-a"}).status_code == 409
        assert not client.get("/api/lab/snapshot").json()["jobs"]


def test_model_failure_and_duplicate_task_are_visible(service, monkeypatch):
    async def failed(*args):
        raise RuntimeError("test model unavailable")

    monkeypatch.setattr(service, "run_team", failed)
    with TestClient(create_lab_app(service)) as client:
        assert (
            client.post(
                "/api/lab/control/run", json={"team": "team-a", "prompt": "test"}
            ).status_code
            == 202
        )
        assert wait_operation(client, "failed")["error"] == "test model unavailable"
        assert not any(
            e["kind"] == "control.completed" for e in client.get("/api/lab/events").json()
        )


def test_model_task_cancellation_is_single_flight(service, monkeypatch):
    async def waiting(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "run_team", waiting)
    with TestClient(create_lab_app(service)) as client:
        first = client.post("/api/lab/control/run", json={"team": "team-a", "prompt": "test"})
        assert (
            client.post(
                "/api/lab/control/run", json={"team": "team-a", "prompt": "again"}
            ).status_code
            == 409
        )
        client.post(
            "/api/lab/control/operations/" + first.json()["operation_id"] + "/cancel", json={}
        )
        wait_operation(client, "cancelled")


def test_a2a_dispatch_and_interteam_message_use_same_store(service, monkeypatch):
    async def run(team, prompt, key):
        assert team == "team-a" and prompt == "test task"
        return "unified result"

    monkeypatch.setattr(service, "run_team", run)
    result = asyncio.run(
        TeamSwarm(service).respond('{"team":"team-a","task":"test task"}', "context")
    )
    assert result == "unified result"
    service.join("team-b", model="deepseek")
    response = asyncio.run(
        TeamSwarm(service).respond(
            json.dumps(
                {
                    "action": "message",
                    "team": "team-a",
                    "recipient": "team-b",
                    "message": "observed result",
                }
            ),
            "context",
        )
    )
    assert json.loads(response)["transport"] == "a2a"
    assert service.store.messages("team-b")[0]["message"] == "observed result"


def test_no_secrets_in_analysis_subprocess_environment(service):
    with patch.dict(
        "os.environ",
        {"AWORKER_LAB_PROVIDER_KEYS": "private", "OPENAI_API_KEY": "private", "PATH": "tools"},
    ):
        env = service.settings.analysis_environment()
    assert "OPENAI_API_KEY" not in env and "AWORKER_LAB_PROVIDER_KEYS" not in env
    assert env["PATH"] == "tools"


# ---- Windows UTF-8 file tools -----------------------------------------------
def test_ripgrep_utf8_chinese_path_and_match_limit(tmp_path):
    folder = tmp_path / "中文路径"
    folder.mkdir()
    (folder / "算子.md").write_text("中文规则\n中文规则\n中文规则\n", encoding="utf-8")
    backend = UTF8FilesystemBackend(root_dir=folder, virtual_mode=True)
    result = backend.grep("中文规则", max_count=2)
    assert len(result.matches) == 2
    assert result.truncated
    assert result.matches[0]["path"] == "/算子.md"


def test_chatgpt_transport_serializes_tool_calls():
    registry = ModelRegistry(Settings(_env_file=None))
    model = registry.build("gpt-chatgpt")
    assert model.model_kwargs["parallel_tool_calls"] is False


# ---- A2A public streaming lifecycle -----------------------------------------
def test_a2a_stream_enqueues_task_before_status_updates(service):
    service.join("team-b", model="deepseek")
    command = json.dumps(
        {
            "action": "message",
            "team": "team-a",
            "recipient": "team-b",
            "message": "test-only transport",
        }
    )
    with TestClient(create_lab_app(service)) as client:
        response = client.post(
            "/a2a/",
            headers={"A2A-Version": "1.0"},
            json={
                "jsonrpc": "2.0",
                "id": "one",
                "method": "SendStreamingMessage",
                "params": {
                    "message": {
                        "messageId": "test-message",
                        "role": "ROLE_USER",
                        "parts": [{"text": command}],
                    }
                },
            },
        )
        assert response.status_code == 200
        assert "TASK_STATE_COMPLETED" in response.text
        assert "Agent should enqueue" not in response.text
    assert service.store.messages("team-b")[0]["message"] == "test-only transport"


# ---- portable execution evidence --------------------------------------------
def test_export_preserves_sources_without_device_lease_tokens(service):
    service.store.join("retired-native", "deepagents", "gpt-chatgpt")
    service.store.register_device("device", "fixture", 0)
    job = service.store.enqueue("team-a")
    lease = service.store.claim(job)
    exported = execution_record(service)
    assert lease["token"] not in json.dumps(exported)
    assert exported["sources"]["team-a"]["sha256"]
    assert len(exported["challenge"]["cases"]) == 15
    service.store.finish(job, lease["token"])


# ---- long-running A2A model tasks -------------------------------------------
def test_a2a_client_timeout_supports_model_and_compile_delays(monkeypatch):
    from a2a.types import Message, Part, StreamResponse

    from aworker.server import client as transport

    seen = {}

    class FakeClient:
        async def send_message(self, request):
            yield StreamResponse(message=Message(parts=[Part(text="test response")]))

        async def close(self):
            seen["closed"] = True

    async def create(url, client_config):
        seen["read_timeout"] = client_config.httpx_client.timeout.read
        return FakeClient()

    monkeypatch.setattr(transport, "create_client", create)
    assert (
        asyncio.run(transport.send_text_message("http://fixture", "test task")) == "test response"
    )
    assert seen["read_timeout"] >= 600 and seen["closed"]


# ---- engineering failure recovery ------------------------------------------
def test_compile_failure_returns_evidence_and_agent_can_retry(service, monkeypatch):
    class FixtureRunner:
        calls = 0

        def evaluate(self, team, source, run_id):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("fixture compiler diagnostic: test-only failure")
            return {"pass": True, "fixture_only": True}

    service.runner = FixtureRunner()
    model = ScriptedModel(
        responses=[
            AIMessage("", tool_calls=[{"id": "one", "name": "evaluate_kernel", "args": {}}]),
            AIMessage("", tool_calls=[{"id": "two", "name": "evaluate_kernel", "args": {}}]),
            AIMessage("fixture recovery completed"),
        ]
    )
    monkeypatch.setattr(service.registry, "build", lambda key: model)
    assert asyncio.run(service.run_team("team-a", "test recovery")) == "fixture recovery completed"
    assert service.runner.calls == 2
    assert any(
        e["kind"] == "tool.completed"
        and "fixture compiler diagnostic" in e["data"].get("output", "")
        for e in service.store.events()
    )


def test_team_cannot_read_other_teams_evaluation_logs(service):
    tools = EngineeringTools(service, "team-a", "run", service.team_folder("team-a"))
    reader = next(t for t in tools.build() if t.name == "read_evaluation_log")
    result = json.loads(reader.invoke({"job_id": "foreign-job"}))
    assert "error" in result


# ---- launcher process ownership --------------------------------------------
def test_cli_records_and_cleans_its_actual_server_pid(tmp_path, monkeypatch):
    import os

    from aworker.lab import cli

    folder = tmp_path / "cli-lab"
    monkeypatch.setattr("sys.argv", ["justkernel", "--root", str(folder), "serve"])
    monkeypatch.setattr(
        cli, "Settings", lambda **values: Settings(_env_file=None, lab_ssh_host=None, **values)
    )

    def run(*args, **kwargs):
        assert (folder / "service.pid").read_text() == str(os.getpid())

    monkeypatch.setattr(cli.uvicorn, "run", run)
    cli.main()
    assert not (folder / "service.pid").exists()

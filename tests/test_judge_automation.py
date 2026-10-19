"""Explicit local transport fixtures; no real account, model, submission or scores."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from pydantic import SecretStr

from aworker.config import Settings
from aworker.lab import judge_automation as automation_module
from aworker.lab.judge_browser import (
    JudgeBrowser,
    JudgeRejected,
    LoginRequired,
    SubmissionUncertain,
    TemplateChanged,
)
from aworker.lab.project import project_manifest
from aworker.lab.service import LabService
from aworker.lab.tools import EngineeringTools


# ---- local delivery fixture, no official site or model calls -----------------
async def deliver_fixture_notices(lab):
    from unittest.mock import patch

    from aworker.lab.bridge import deliver_message

    async def send(notice):
        return deliver_message(
            lab,
            json.dumps(
                {
                    "action": "message",
                    "team": "judger",
                    "recipient": notice.recipient,
                    "message": notice.message,
                    "artifact": notice.artifact,
                    "delivery_id": notice.id,
                }
            ),
        )

    with patch.object(lab, "send_notice", send):
        await lab.judger.notices.flush()


# ---- source and transport fixtures ------------------------------------------
@pytest.fixture
def lab(tmp_path):
    service = LabService(
        Settings(
            lab_root=tmp_path / "lab",
            lab_private_root=tmp_path / "private",
            lab_provider_keys={"openai": SecretStr("fixture")},
            _env_file=None,
        )
    )
    service.auto_teams(1, "gpt-api")
    folder = service.team_folder("gpt-001") / "project"
    # Deliberately NOT a valid kernel. Only the source binding protocol is tested.
    (folder / "op_kernel/confusion_mul_grad.h").write_text(
        "// fixture only, no execution claim\nvoid Init(){return;} void Process(){return;}\n",
        encoding="utf8",
    )
    for name in [
        "op_host/confusion_mul_grad_tiling.cpp",
        "op_host/confusion_mul_grad_infershape.cpp",
    ]:
        (folder / name).write_text("// fixture only\nint fixture(){return 1;}\n", encoding="utf8")
    return service


# ---- FakeBrowser ------------------------------------------------------------
class FakeBrowser:
    def __init__(self, lab):
        self.lab = lab
        self.calls = []
        self.failure = None

    def status(self):
        return {
            "opened": True,
            "connected": True,
            "state": "connected",
            "message": "fixture session",
        }

    async def call(self, method, *args):
        self.calls.append((method, args))
        manifest = project_manifest(self.lab.root)
        if method == "template":
            return {
                "files": [
                    {
                        "path": p,
                        "content": (self.lab.root / "challenge/project" / p).read_bytes().decode(),
                        "editable": p in manifest["editable_paths"],
                    }
                    for p in manifest["project_files"]
                ]
            }
        if method == "submit":
            if self.failure:
                raise self.failure
            return "a" * 24
        if method == "receipt":
            return {
                "problem_id": manifest["input_source"]["problem_id"],
                "status": "Pass",
                "score": 7.5,
                "result": [{"testcase_status": "Hidden", "msg": "fixture-hidden-details"}],
            }
        if method == "check":
            return self.status()
        raise AssertionError("unexpected fixture method " + method)

    async def close(self):
        pass


# ---- connected_lab ----------------------------------------------------------
def connected_lab(lab):
    browser = FakeBrowser(lab)
    lab.judger.browser = browser
    lab.judger.automation.browser = browser
    # These transport tests never dispatch a real model; the selector graph is tested separately.
    lab.judger.automation.selector.schedule = lambda: None
    row = lab.judger.stage("gpt-001")
    return browser, row


# ---- exact payload and independent source review ----------------------------
def test_auto_submit_requires_source_bound_review_then_sends_only_seven_files(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    with pytest.raises(ValueError, match="reviewer"):
        asyncio.run(auto.submit(row["id"]))
    assert not browser.calls
    auto.review("gpt-001", True, "fixture source review; no correctness or compilation claim")
    result = asyncio.run(auto.submit(row["id"]))
    assert result["submission_id"] == "a" * 24
    payload = next(args for method, args in browser.calls if method == "submit")
    assert payload[0] == project_manifest(lab.root)["input_source"]["problem_id"]
    assert {f["path"] for f in payload[1]} == set(project_manifest(lab.root)["editable_paths"])
    assert len(payload[1]) == 7
    stored = lab.judger.read("queue.json", [])[0]
    assert stored["binding"] == "browser-session"
    assert stored["source_sha256"] == row["source_sha256"]
    with pytest.raises(ValueError, match="重复"):
        asyncio.run(auto.submit(row["id"]))


def test_ambiguous_post_never_retries_or_fabricates_submission(lab):
    browser, row = connected_lab(lab)
    lab.judger.automation.review("gpt-001", True, "fixture only, ready for submission protocol")
    browser.failure = SubmissionUncertain("fixture response timeout")
    with pytest.raises(SubmissionUncertain):
        asyncio.run(lab.judger.automation.submit(row["id"]))
    stored = lab.judger.read("queue.json", [])[0]
    assert stored["state"] == "submission-uncertain"
    assert stored["official_submission_id"] is None
    with pytest.raises(ValueError):
        asyncio.run(lab.judger.automation.submit(row["id"]))
    assert sum(m == "submit" for m, _ in browser.calls) == 1


def test_frozen_review_survives_new_work_and_rate_limit_is_respected(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture independent source review")
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_text(path.read_text() + "// changed\n", encoding="utf8")
    frozen = lab.judger.read("queue.json", [])[0]
    assert auto.readiness(frozen)[0]
    row = lab.judger.stage("gpt-001")
    assert not auto.readiness(row)[0]
    auto.review("gpt-001", True, "fixture new version reviewed independently")
    browser.failure = JudgeRejected("fixture rate limit", 120)
    with pytest.raises(JudgeRejected):
        asyncio.run(auto.submit(row["id"]))
    assert auto.configuration()["next_submission_after"] >= time.time() + 119
    assert lab.judger.read("queue.json", [])[-1]["state"] == "awaiting-submit-slot"


def test_receipt_path_masks_hidden_details_and_broadcasts_without_overwriting_teams(
    lab, monkeypatch
):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture independent source review")
    calls = []
    monkeypatch.setattr(lab, "start_operation", lambda *args: calls.append(args) or "fixture-op")

    async def scenario():
        await auto.submit(row["id"])
        lab.judger.write("automation.json", {"enabled": True, "max_rounds": 3})
        await auto.tick()
        await auto.tick()
        await deliver_fixture_notices(lab)

    asyncio.run(scenario())
    stored = lab.judger.read("queue.json", [])[0]
    assert stored["official"]["score"] == 7.5
    assert stored["official"]["result"] == [{"testcase_status": "Hidden"}]
    assert stored["feedback_broadcast_hash"]
    assert len(lab.store.messages("gpt-001")) == 2
    assert not calls
    assert not any(e["kind"] == "evaluation.completed" for e in lab.store.events())


def test_only_reviewer_gets_the_approval_tool(lab):
    tools = EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001"))
    assert "record_review" not in {t.name for t in tools.build()}
    assert "record_review" not in {t.name for t in tools.build(read_only=True, role="analyst")}
    assert "record_review" in {t.name for t in tools.build(read_only=True, role="reviewer")}


def test_reviewer_cannot_apply_old_approval_to_new_source(lab):
    tools = EngineeringTools(lab, "gpt-001", "fixture", lab.team_folder("gpt-001"))
    record = next(
        t for t in tools.build(read_only=True, role="reviewer") if t.name == "record_review"
    )
    digest = lab.candidate("gpt-001")["sha256"]
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_text(path.read_text() + "// changed during review\n", encoding="utf8")
    with pytest.raises(ValueError, match="复核期间发生变化"):
        record.invoke({"source_sha256": digest, "ready": True, "notes": "fixture old review"})
    assert not any(r.get("review") for r in lab.judger.read("queue.json", []))


# ---- owner identity comes from a fresh login context, not a supplied ID ------
class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body
        self.ok = status == 200
        self.headers = {}

    async def json(self):
        return self.body


# ---- RequestFixture ---------------------------------------------------------
class RequestFixture:
    def __init__(self):
        self.calls = []
        self.authenticated = True

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return Response(
            200 if self.authenticated else 401, {"_id": "b" * 24, "ID": 123, "nickname": "fixture"}
        )

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return Response(200, {"code": 0, "data": {"submissionId": "c" * 24}})


# ---- PageFixture ------------------------------------------------------------
class PageFixture:
    url = "https://cannjudge.cn/public/ladder_october/confusionmulgrad/submit"

    def is_closed(self):
        return False

    async def evaluate(self, script):
        assert "cannjudge_user" in script
        return {"_id": "b" * 24, "ID": 123}


def test_browser_transport_validates_logged_in_identity_and_does_not_expose_credentials(lab):
    worker = JudgeBrowser(lab.settings)
    request = RequestFixture()
    worker.page = PageFixture()
    worker.context = type("Context", (), {"request": request})()
    assert (
        asyncio.run(worker._submit("d" * 24, [{"path": "fixture", "content": "fixture"}]))
        == "c" * 24
    )
    post = request.calls[-1]
    assert post[1] == "https://cannjudge.cn/api/submissions/submit"
    assert post[2]["data"]["userId"] == "b" * 24
    assert post[2]["max_retries"] == 0
    assert "userId" not in worker.status()
    request.authenticated = False
    with pytest.raises(LoginRequired):
        asyncio.run(worker._submit("d" * 24, []))
    assert sum(method == "POST" for method, _, _ in request.calls) == 1


# ---- isolated worker lifecycle and boundaries -------------------------------
def test_browser_worker_has_private_temp_and_closes_without_browser(lab, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret-not-for-browser")
    monkeypatch.setenv("AWORKER_LAB_PROVIDER_KEYS", '{"openai":"fixture-secret"}')
    temporary = lab.settings.lab_private_root / "browser-temporary"
    env = lab.settings.judge_browser_environment(temporary)
    assert env["TEMP"] == env["TMP"] == env["TMPDIR"] == str(temporary.resolve())
    assert "DEEPSEEK_API_KEY" not in env and "AWORKER_LAB_PROVIDER_KEYS" not in env
    with pytest.raises(ValueError, match="private root"):
        lab.settings.judge_browser_environment(lab.settings.lab_root)
    browser = JudgeBrowser(lab.settings)

    async def scenario():
        result = await browser.call("check")
        assert not result["connected"] and not result["opened"]
        with pytest.raises(LoginRequired, match="请从面板打开"):
            await browser.call("submit", "d" * 24, [{"path": "中文", "content": "中文"}])
        process = browser.process
        folder = browser.temporary.name
        await browser.close()
        assert process.poll() is not None
        return folder

    from pathlib import Path

    assert not Path(asyncio.run(scenario())).exists()


def test_account_changed_between_check_and_submit_never_posts(lab):
    worker = JudgeBrowser(lab.settings)
    request = RequestFixture()
    worker.page = PageFixture()
    worker.context = type("Context", (), {"request": request})()
    with pytest.raises(LoginRequired, match="账户已改变"):
        asyncio.run(worker._submit("d" * 24, [], "different-account-hash"))
    assert all(method != "POST" for method, _, _ in request.calls)


def test_auto_pause_while_checking_template_leaves_candidate_unsent(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture source review only")
    auto.selector.nominate(
        row["id"], row["source_sha256"], "fixture-only comparison; no measured speed claim"
    )
    original = browser.call

    async def paused(method, *args):
        result = await original(method, *args)
        if method == "template":
            lab.judger.write("automation.json", {"enabled": False, "max_rounds": 3})
        return result

    browser.call = paused
    result = asyncio.run(auto.submit(row["id"], automatic=True))
    assert result["state"] == "paused"
    assert not any(m == "submit" for m, _ in browser.calls)
    assert not lab.judger.read("queue.json", [])[0]["official_submission_id"]


def test_official_template_change_stops_before_submission(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture source review only")
    original = browser.call

    async def changed(method, *args):
        result = await original(method, *args)
        if method == "template":
            result["files"][0]["content"] += "\n// new official template fixture"
        return result

    browser.call = changed
    with pytest.raises(TemplateChanged):
        asyncio.run(auto.submit(row["id"]))
    assert not any(m == "submit" for m, _ in browser.calls)
    assert lab.judger.read("queue.json", [])[0]["state"] == "blocked-template"


# ---- continuous search, global champion selection and shared feedback -------
def test_each_team_advances_without_waiting_for_other_teams_or_login(lab, monkeypatch):
    lab.auto_teams(1, "gpt-api")
    calls = []

    def launch(team, kind, prompt):
        key = "fixture-op-" + str(len(calls))
        lab.store.operation(key, team, kind)
        calls.append((team, key, prompt))
        return key

    monkeypatch.setattr(lab, "start_operation", launch)
    lab.swarm.write({"enabled": True, "strategy": "parallel", "turn_interval": 5})
    lab.swarm.tick()
    assert {c[0] for c in calls} == {"gpt-001", "gpt-002"}
    assert not lab.judger.browser.status()["connected"]
    first = next(c for c in calls if c[0] == "gpt-001")
    lab.store.operation_finished(first[1], "completed")
    lab.swarm.tick()
    state = lab.swarm.read()
    state["progress"]["gpt-001"]["next_at"] = 0
    lab.swarm.write(state)
    lab.swarm.tick()
    assert len(calls) == 3 and calls[-1][0] == "gpt-001"
    assert "read_team_messages" in calls[-1][2]
    assert (
        next(o for o in lab.store.snapshot()["operations"] if o["team"] == "gpt-002")["state"]
        == "running"
    )
    assert not any(e["kind"] == "judge.submitted" for e in lab.store.events())


def test_official_submission_uses_frozen_code_while_team_keeps_working(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture exact frozen source review")
    auto.selector.nominate(
        row["id"],
        row["source_sha256"],
        "fixture-only strongest challenger comparison; no timing claim",
    )
    lab.judger.write("automation.json", {"enabled": True, "max_submissions": 50})
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_text(path.read_text() + "// NEW-WORK-IN-PROGRESS\n", encoding="utf8")
    lab.store.operation("fixture-active", "gpt-001", "run")
    result = asyncio.run(auto.submit(row["id"], automatic=True))
    assert result["submission_id"]
    payload = next(args[1] for method, args in browser.calls if method == "submit")
    assert all("NEW-WORK-IN-PROGRESS" not in f["content"] for f in payload)
    assert "NEW-WORK-IN-PROGRESS" in path.read_text()
    assert lab.store.snapshot()["operations"][0]["state"] == "running"


def test_daily_50_attempt_budget_survives_pause_restart_and_resets_by_shanghai_day(
    lab, monkeypatch
):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture only, source protocol review")
    for number in range(50):
        auto.reserve_attempt({"id": str(number), "at": time.time()})
    assert auto.budget()["used"] == 50 and auto.budget()["remaining"] == 0
    calls = []
    monkeypatch.setattr(
        lab, "start_operation", lambda *args: calls.append(args) or "fixture-search"
    )
    lab.swarm.write({"enabled": True})
    lab.swarm.tick()
    assert len(calls) == 1
    with pytest.raises(ValueError, match="预算"):
        asyncio.run(auto.submit(row["id"]))
    assert not browser.calls
    asyncio.run(auto.configure(False, 50))
    from aworker.lab.judger import JudgeMonitor

    assert JudgeMonitor(lab).automation.budget()["used"] == 50

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1)

    monkeypatch.setattr(automation_module, "datetime", NextDay)
    assert auto.budget()["used"] == 0 and auto.budget()["remaining"] == 50
    assert len(auto.attempts()) == 50


def test_ambiguous_submission_consumes_daily_budget_and_is_globally_deduplicated(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture source protocol review")
    browser.failure = SubmissionUncertain("fixture timeout")
    with pytest.raises(SubmissionUncertain):
        asyncio.run(auto.submit(row["id"]))
    assert auto.budget()["used"] == 1
    assert not auto.selector.pool()


def test_only_verified_official_passes_promote_champion_and_feedback_reaches_busy_teams(lab):
    _, row = connected_lab(lab)
    lab.auto_teams(1, "gpt-api")
    lab.store.operation("busy-fixture", "gpt-002", "run")
    auto = lab.judger.automation
    auto.update(
        row["id"],
        binding="browser-session",
        official_submission_id="a" * 24,
        official={"status": "Pass", "score": 10, "result": []},
    )
    lab.judger.broadcast_feedback()
    asyncio.run(deliver_fixture_notices(lab))
    assert lab.judger.champion()["id"] == row["id"]
    assert len(lab.store.messages("gpt-001")) == len(lab.store.messages("gpt-002")) == 2
    auto.update(row["id"], feedback_broadcast_hash=None)
    lab.judger.broadcast_feedback()
    asyncio.run(deliver_fixture_notices(lab))
    assert len(lab.store.messages("gpt-002")) == 2
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_text(path.read_text() + "// second fixture source\n", encoding="utf8")
    lower = lab.judger.stage("gpt-001")
    auto.update(
        lower["id"],
        binding="browser-session",
        official_submission_id="b" * 24,
        official={"status": "Pass", "score": 5, "result": []},
    )
    assert lab.judger.champion()["id"] == row["id"]
    auto.update(lower["id"], binding="user-reported", official={"status": "Pass", "score": 100})
    assert lab.judger.champion()["id"] == row["id"]
    auto.update(lower["id"], binding="browser-session", official={"status": "Fail", "score": 1000})
    assert lab.judger.champion()["id"] == row["id"]


def test_concurrent_team_freezing_does_not_lose_candidates(lab):
    lab.auto_teams(7, "gpt-api")
    for index in range(2, 9):
        path = lab.team_folder(f"gpt-{index:03d}") / "project/op_kernel/confusion_mul_grad.h"
        path.write_text(f"// explicit staging fixture {index}\n", encoding="utf8")
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lab.judger.stage, [f"gpt-{i:03d}" for i in range(1, 9)]))
    assert len({r["id"] for r in rows}) == len(lab.judger.read("queue.json", [])) == 8


def test_real_deep_agent_selector_graph_reviews_and_nominates_one_snapshot(lab, monkeypatch):
    from langchain_core.messages import AIMessage
    from test_unified_lab import ScriptedModel

    offered = []

    def bind_tools(model, tools, **kwargs):
        offered.append({t.name for t in tools})
        return model

    monkeypatch.setattr(ScriptedModel, "bind_tools", bind_tools)
    _, row = connected_lab(lab)
    calls = [
        ("read_spec", {}),
        ("list_candidates", {}),
        ("read_candidate", {"candidate_id": row["id"]}),
        (
            "review_candidate",
            {
                "candidate_id": row["id"],
                "source_sha256": row["source_sha256"],
                "ready": True,
                "notes": "fixture source review only, no execution claim",
            },
        ),
        (
            "nominate_candidate",
            {
                "candidate_id": row["id"],
                "source_sha256": row["source_sha256"],
                "reason": "fixture-only initial baseline nomination; no measured speed claim",
            },
        ),
    ]
    model = ScriptedModel(
        responses=[
            AIMessage(content="", tool_calls=[{"id": f"fixture-{i}", "name": name, "args": args}])
            for i, (name, args) in enumerate(calls)
        ]
        + [AIMessage(content="Fixture selection complete; this is not a real optimization result.")]
    )
    monkeypatch.setattr(lab.registry, "build", lambda _: model)
    selector = lab.judger.automation.selector
    asyncio.run(selector.run("gpt-api", selector.fingerprint()))
    assert selector.state()["phase"] == "nominated", selector.state()
    assert selector.nomination()["candidate_id"] == row["id"]
    assert not lab.judger.read("queue.json", [])[0].get("official_submission_id")
    assert lab.judger.read("queue.json", [])[0]["review"]["reviewer"] == "independent-selector"
    assert offered and all(
        names
        == {
            "read_spec",
            "list_candidates",
            "read_candidate",
            "review_candidate",
            "nominate_candidate",
        }
        for names in offered
    )


def test_feedback_arriving_mid_turn_is_visible_at_next_model_step(lab, monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage
    from test_unified_lab import ScriptedModel

    from aworker.lab.deepagent import DeepAgentRuntime

    observed = []

    class InboxModel(ScriptedModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            observed.append(list(messages))
            if len(observed) == 1:
                lab.store.message("controller", "gpt-001", "MIDTURN-FEEDBACK-FIXTURE", None)
            return super()._generate(messages, stop, run_manager, **kwargs)

    model = InboxModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"id": "fixture-tool", "name": "inspect_policy", "args": {}}],
            ),
            AIMessage(content="Fixture update received; no real measurement."),
        ]
    )
    monkeypatch.setattr(lab.registry, "build", lambda _: model)
    graph = DeepAgentRuntime(lab, "gpt-001", "fixture-midturn").build("gpt-api", None)
    asyncio.run(graph.ainvoke({"messages": [HumanMessage("Fixture source review.")]}))
    assert not any("MIDTURN-FEEDBACK-FIXTURE" in str(m.content) for m in observed[0])
    assert any("MIDTURN-FEEDBACK-FIXTURE" in str(m.content) for m in observed[1])
    assert any(e["kind"] == "shared.feedback.loaded" for e in lab.store.events())


def test_judger_sends_only_the_nominated_candidate_not_every_reviewed_version(lab):
    browser, first = connected_lab(lab)
    auto = lab.judger.automation
    auto.review("gpt-001", True, "fixture first frozen source review")
    path = lab.team_folder("gpt-001") / "project/op_kernel/confusion_mul_grad.h"
    path.write_text(path.read_text() + "// second distinct fixture\n", encoding="utf8")
    second = lab.judger.stage("gpt-001")
    auto.review("gpt-001", True, "fixture second frozen source review")
    auto.selector.nominate(
        first["id"],
        first["source_sha256"],
        "fixture comparison chooses first snapshot, not a measured result",
    )
    lab.judger.write("automation.json", {"enabled": True, "max_submissions": 50})
    with pytest.raises(ValueError, match="只提交"):
        asyncio.run(auto.submit(second["id"], automatic=True))
    assert not browser.calls
    asyncio.run(auto.submit(first["id"], automatic=True))
    queue = lab.judger.read("queue.json", [])
    assert queue[0]["official_submission_id"] and not queue[1]["official_submission_id"]


@pytest.mark.parametrize(
    "failure,expected_launches", [("fixture browser crash", 2), ("blocked by policy", 1)]
)
def test_browser_runtime_fallback_keeps_sandbox_and_does_not_retry_policy_denial(
    lab, monkeypatch, tmp_path, failure, expected_launches
):
    import playwright.async_api

    binary = tmp_path / "fixture-browser-not-executed"
    binary.write_text("fixture only")
    launches = []

    class Page:
        url = "https://cannjudge.cn/"

        def is_closed(self):
            return False

        async def goto(self, *args, **kwargs):
            pass

        async def evaluate(self, *args):
            return None

    class Context:
        async def new_page(self):
            return Page()

        async def close(self):
            pass

    class Browser:
        async def new_context(self, **kwargs):
            return Context()

        async def close(self):
            pass

    class Chromium:
        executable_path = str(binary)

        async def launch(self, **kwargs):
            launches.append(kwargs)
            if len(launches) == 1:
                raise RuntimeError(failure)
            return Browser()

    class Driver:
        chromium = Chromium()

        async def start(self):
            return self

        async def stop(self):
            pass

    monkeypatch.setattr(playwright.async_api, "async_playwright", Driver)
    worker = JudgeBrowser(lab.settings.model_copy(update={"lab_judge_browser_channel": "chrome"}))
    if expected_launches == 1:
        with pytest.raises(ValueError, match="未能启动"):
            asyncio.run(worker._open("https://cannjudge.cn/"))
    else:
        assert asyncio.run(worker._open("https://cannjudge.cn/"))["state"] == "awaiting-login"
    assert len(launches) == expected_launches
    assert all(call["chromium_sandbox"] is True and call["headless"] is False for call in launches)


# ---- missing evidence must not masquerade as a running selector --------------
def test_no_qualified_candidate_is_explicitly_waiting_not_selecting(lab):
    connected_lab(lab)
    auto = lab.judger.automation
    lab.settings = lab.settings.model_copy(update={"lab_require_simulation": True})
    lab.judger.write("automation.json", {"enabled": True, "max_submissions": 50})
    asyncio.run(auto.tick())
    assert auto.phase == "awaiting-qualified-candidate"
    assert "完整仿真" in auto.message
    assert auto.budget()["used"] == 0
    assert not auto.selector.status()["running"]


# ---- a new challenger must not wait behind repeated reads of old terminal failures ----
def test_official_lane_skips_old_terminal_receipts_but_accepts_rank_updates(lab):
    browser, row = connected_lab(lab)
    auto = lab.judger.automation
    auto.update(
        row["id"],
        official_submission_id="a" * 24,
        binding="browser-session",
        official={"status": "Wrong Answer", "score": None, "rank": None, "result": []},
    )
    asyncio.run(lab.judger.refresh_tracked([], include_terminal=False))
    assert not browser.calls
    asyncio.run(
        lab.judger.refresh_tracked(
            [{"submission_id": "a" * 24, "rank": 12}], include_terminal=False
        )
    )
    assert not browser.calls
    assert lab.judger.read("queue.json", [])[0]["official"]["rank"] == 12

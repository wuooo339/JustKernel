from __future__ import annotations

from fastapi.testclient import TestClient

from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeArtifactStore,
    FakeIds,
    FakeMessageBus,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryDirectionRepository,
    InMemoryReportRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.source import SourceRevision
from justkernel.cluster.direction import Direction
from justkernel.cluster.operator_spec import (
    AccuracyPolicy,
    CasePackRef,
    OperatorRef,
    OutputTolerance,
    ReferenceSpec,
)
from justkernel.cluster.state import DirectionState, StartMode
from justkernel.comm.channels import Channel
from justkernel.comm.message import Message, MessageType
from justkernel.platform.http.app import create_app
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.request_models import ClusterCreateBody, SkillPayload
from justkernel.report.report import ExplorationReport, ReportDirection
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId, MessageId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.shared.principal import Principal
from justkernel.task.state import TaskKind
from justkernel.testing.job import ToolJob, ToolJobState
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- fixture ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation-test",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _fixture() -> tuple[TestClient, dict[str, object]]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    jobs = InMemoryToolJobRepository()
    directions = InMemoryDirectionRepository()
    reports = InMemoryReportRepository()
    messages = FakeMessageBus()
    artifacts = FakeArtifactStore()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    cluster = cluster_service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    cluster_service.start_cluster(cluster.id)
    agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.SUPERVISOR,
        model_profile="model-1",
        skills=(),
        agent_id=cluster.supervisor_id,
    )
    mentor = agent_service.create_agent(
        cluster_id=cluster.id,
        role=Role.MENTOR,
        model_profile="model-1",
        skills=(),
    )
    tester = agent_service.open_worker(
        mentor_id=mentor.id,
        role=Role.TESTER,
        model_profile="model-1",
        skills=(_skill(),),
    )
    candidate = CandidateVersion(
        id=CandidateId.generate(),
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        parent_id=None,
        author_agent_id=None,
        author_principal=Principal.system(),
        task_id=None,
        import_id="import-1",
        source=SourceRevision.from_files({"kernel.cpp": "// source"}),
        diff_artifact="artifact://diff",
        created_at=0,
    )
    candidates.insert(candidate)
    direction = Direction(
        id=candidate.direction_id,
        cluster_id=cluster.id,
        mentor_id=mentor.id,
        objective="baseline",
        created_at=0,
        state=DirectionState.ACTIVE,
    )
    directions.insert(direction)
    task = agent_service.assign_task(
        mentor_id=mentor.id,
        worker_id=tester.id,
        kind=TaskKind.TEST,
        direction_id=direction.id,
        operator_spec_ref=_operator_ref(),
        context_ref="artifact://context",
        context_digest=Digest.from_text("context"),
        budget_ref="budget-1",
        objective="test",
        candidate_id=candidate.id,
        skill_ref=_skill(),
        created_at=0,
    )
    job = ToolJob(
        id="job-1",
        task_id=task.id,
        candidate_id=candidate.id,
        request_digest=Digest.from_text("request"),
        state=ToolJobState.RUNNING,
        created_at=0,
        started_at=0,
        execution_timeout_s=30,
    )
    jobs.insert(job)
    zip_digest = artifacts.put_bytes(b"record zip")
    record = Record(
        id=RecordId.generate(),
        candidate_id=candidate.id,
        kind=RecordKind.TEST,
        skill_ref=_skill(),
        backend="cann-simulation",
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        executed=True,
        artifact=ArtifactRef(ref="artifact://record", digest=zip_digest),
        environment=Environment(values=(("soc", "Ascend910B4"),)),
        created_at=0,
        task_id=task.id,
        job_id=job.id,
    )
    records.append(record)
    report = ExplorationReport(
        id="report-1",
        cluster_id=cluster.id,
        best_candidate_id=candidate.id,
        revision=1,
        directions=(
            ReportDirection(direction_id=direction.id, objective="baseline", outcome="pass"),
        ),
        candidates=(candidate.id,),
        records=(record.id,),
        failures=(),
        decision="complete",
        created_at=0,
    )
    reports.append(report)
    cluster_service.attach_report(cluster.id, report.id)
    messages.publish(
        Message(
            id=MessageId.generate(),
            cluster_id=cluster.id,
            seq=1,
            channel=Channel.mentor_board(),
            type=MessageType.MENTOR_SUMMARY,
            sender=Principal.agent(mentor.id),
            created_at=0,
            payload={"summary": "baseline"},
        )
    )
    context = ApiContext(
        clusters=clusters,
        agents=agents,
        tasks=tasks,
        candidates=candidates,
        records=records,
        jobs=jobs,
        directions=directions,
        reports=reports,
        messages=messages,
        artifacts=artifacts,
        cluster_service=cluster_service,
        now_ms=lambda: 100,
    )
    client = TestClient(create_app(context=context))
    ids_map = {
        "cluster": cluster.id.value,
        "mentor": mentor.id.value,
        "tester": tester.id.value,
        "task": task.id.value,
        "candidate": candidate.id.value,
        "record": record.id.value,
        "job": job.id,
    }
    return client, ids_map


# ---- create request mapping -------------------------------------------------
def test_cluster_create_body_maps_to_start_request() -> None:
    reference = ReferenceSpec(
        kind="executable",
        description="reference",
        artifact_digest=Digest.from_text("reference"),
    )
    accuracy = AccuracyPolicy(
        outputs=(OutputTolerance(dtype="float32", atol=1e-5, rtol=1e-5),),
    )
    case_pack = CasePackRef(digest=Digest.from_text("cases"), case_count=10, seed=7)
    payload = ClusterCreateBody(
        operator_spec={
            "operator_id": "op-1",
            "version": "1",
            "semantics": "semantics",
            "input_contract": "float32",
            "reference": {
                "kind": "executable",
                "description": "reference",
                "artifact_digest": reference.artifact_digest.value,
            },
            "accuracy_policy": {
                "outputs": [{"dtype": "float32", "atol": 1e-5, "rtol": 1e-5}],
            },
            "case_pack": {
                "digest": case_pack.digest.value,
                "case_count": 10,
                "seed": 7,
            },
            "target": {
                "soc": "Ascend910B4",
                "language": "cpp",
                "abi": "aclnn",
                "cann_version": "9.0.0",
                "build_entry": "build.sh",
                "run_entry": "run.sh",
            },
            "engineering_policy": {
                "editable_paths": ["op/kernel.cpp"],
                "read_only_paths": ["tests/cases.json"],
                "forbidden_actions": ["modify oracle"],
            },
            "evaluation_policy": {
                "case_pack_digest": case_pack.digest.value,
                "reference_digest": reference.digest().value,
                "accuracy_policy_digest": accuracy.digest().value,
                "allowed_backends": ["cann-simulation"],
                "environment_fingerprint": "env",
                "timing_unit": "ms",
                "warmup": 1,
                "repeats": 3,
                "aggregation": "median",
            },
        },
        operator_artifact_ref="artifact://spec",
        start_mode="GENERATE",
        tester_skill=SkillPayload(
            name="tester-cann-simulation",
            version="1",
            source_path="/skills/tester",
            digest=Digest.from_text("skill").value,
        ),
        backend="cann-simulation",
        model_profile="model",
        budget={"max_duration_s": 60},
        reservation_key="key",
        journal_ref="journal",
    )

    request = payload.to_start_request()

    assert request.operator_spec.operator_id == "op-1"
    assert request.start_mode is StartMode.GENERATE
    assert request.operator_spec.target.soc == "Ascend910B4"


# ---- read routes ------------------------------------------------------------
def test_cluster_agent_direction_and_task_routes() -> None:
    client, ids = _fixture()

    cluster = client.get(f"/api/v1/clusters/{ids['cluster']}")
    agents = client.get(f"/api/v1/clusters/{ids['cluster']}/agents")
    directions = client.get(f"/api/v1/clusters/{ids['cluster']}/directions")
    tasks = client.get(f"/api/v1/tasks?cluster={ids['cluster']}")

    assert cluster.status_code == 200
    assert cluster.json()["state"] == "RUNNING"
    assert cluster.json()["active_agents"] == 3
    assert len(agents.json()) == 3
    assert directions.json()[0]["state"] == "ACTIVE"
    assert tasks.json()[0]["kind"] == "TEST"
    assert client.get(f"/api/v1/agents/{ids['tester']}").json()["role"] == "TESTER"


def test_candidate_record_and_download_routes() -> None:
    client, ids = _fixture()

    candidates = client.get(f"/api/v1/clusters/{ids['cluster']}/candidates")
    records = client.get(f"/api/v1/candidates/{ids['candidate']}/records")
    source = client.get(
        f"/api/v1/candidates/{ids['candidate']}/source",
        headers={"X-Human": "true"},
    )
    record = client.get(f"/api/v1/records/{ids['record']}")
    download = client.get(
        f"/api/v1/records/{ids['record']}/download",
        headers={"X-Human": "true"},
    )

    assert candidates.status_code == 200
    assert candidates.json()[0]["record_count"] == 1
    assert len(records.json()) == 1
    assert source.json()["files"][0]["path"] == "kernel.cpp"
    assert record.json()["outcome"] == "PASS"
    assert download.status_code == 200
    assert download.content == b"record zip"
    assert download.headers["x-artifact-digest"] == record.json()["artifact_digest"]


def test_task_context_and_tool_job_object_acl() -> None:
    client, ids = _fixture()

    allowed = client.get(
        f"/api/v1/tasks/{ids['task']}/context",
        headers={"X-Agent-Id": ids["tester"]},
    )
    denied = client.get(
        f"/api/v1/tasks/{ids['task']}/context",
        headers={"X-Agent-Id": ids["mentor"]},
    )
    missing = client.get(f"/api/v1/tasks/{ids['task']}/context")

    allowed_job = client.get(
        f"/api/v1/tool-jobs/{ids['job']}",
        headers={"X-Agent-Id": ids["tester"]},
    )
    denied_job = client.get(
        f"/api/v1/tool-jobs/{ids['job']}",
        headers={"X-Agent-Id": ids["mentor"]},
    )

    assert allowed.status_code == 200
    assert allowed.json()["context_ref"] == "artifact://context"
    assert denied.status_code == 200
    assert missing.status_code == 403
    assert allowed_job.status_code == 200
    assert allowed_job.json()["job_id"] == ids["job"]
    assert denied_job.status_code == 403


def test_report_board_and_health_routes() -> None:
    client, ids = _fixture()

    report = client.get(f"/api/v1/clusters/{ids['cluster']}/report")
    board = client.get(f"/api/v1/clusters/{ids['cluster']}/board/mentor")
    messages = client.get("/api/v1/messages?channel=mentor_board")
    hardware = client.get("/api/v1/hardware/queue")

    assert report.status_code == 200
    assert report.json()["best_candidate_id"] == ids["candidate"]
    assert board.json()[0]["payload"]["summary"] == "baseline"
    assert messages.json()[0]["channel"] == "mentor_board"
    assert hardware.json() == {"devices": [], "queued": [], "leased": []}


def test_cluster_actions_are_idempotent() -> None:
    client, ids = _fixture()
    headers = {"Idempotency-Key": "pause-key"}

    first = client.post(f"/api/v1/clusters/{ids['cluster']}/pause", headers=headers)
    second = client.post(f"/api/v1/clusters/{ids['cluster']}/pause", headers=headers)
    resumed = client.post(f"/api/v1/clusters/{ids['cluster']}/resume")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["state"] == "PAUSED"
    assert resumed.json()["state"] == "RUNNING"


def test_unknown_resources_return_problem_404() -> None:
    client, _ = _fixture()

    response = client.get("/api/v1/clusters/" + "0" * 32)

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_found"

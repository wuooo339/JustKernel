from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from justkernel.agent.skills import SkillRef
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
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.platform.http.app import create_app
from justkernel.platform.http.context import ApiContext
from justkernel.platform.security.redactor import PRIVATE_PATH, REDACTED, Redactor
from justkernel.report.report import ExplorationReport, ReportDirection
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.shared.principal import Principal
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind

SECRET = "super-secret-value-123"
PRIVATE = str(Path("/home/very-private/justkernel").resolve())


# ---- fixture ----------------------------------------------------------------
def _client() -> tuple[TestClient, dict[str, str]]:
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    reports = InMemoryReportRepository()
    artifacts = FakeArtifactStore()
    ids = FakeIds()
    service = ClusterService(clusters, ids)
    cluster = service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=OperatorRef(
            operator_id="op-1",
            version="1",
            digest=Digest.from_text("spec"),
            artifact_ref="artifact://spec",
        ),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    service.start_cluster(cluster.id)
    candidate = CandidateVersion(
        id=CandidateId.generate(),
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        parent_id=None,
        author_agent_id=None,
        author_principal=Principal.system(),
        task_id=None,
        import_id="import-1",
        source=SourceRevision.from_files(
            {"kernel.cpp": f"// token={SECRET}\n// path={PRIVATE}/\n"}
        ),
        diff_artifact="artifact://diff",
        created_at=0,
    )
    candidates.insert(candidate)
    record = Record(
        id=RecordId.generate(),
        candidate_id=candidate.id,
        kind=RecordKind.TEST,
        skill_ref=SkillRef(
            name="tester",
            version="1",
            source_path="/skills/tester",
            digest=Digest.from_text("skill"),
        ),
        backend="cann-simulation",
        outcome=Outcome.PASS,
        coverage=Coverage.FULL,
        executed=True,
        artifact=ArtifactRef(ref="artifact://record", digest=artifacts.put_bytes(b"zip")),
        environment=Environment(values=(("soc", "Ascend910B4"),)),
        created_at=0,
        task_id=TaskId.generate(),
        job_id="job-1",
        summary=SECRET,
    )
    records.append(record)
    report = ExplorationReport(
        id="report-1",
        cluster_id=cluster.id,
        best_candidate_id=None,
        revision=1,
        directions=(
            ReportDirection(
                direction_id=candidate.direction_id,
                objective=SECRET,
                outcome=PRIVATE,
            ),
        ),
        candidates=(candidate.id,),
        records=(record.id,),
        failures=(f"failure at {PRIVATE} with {SECRET}",),
        decision=f"stop {SECRET}",
        created_at=0,
    )
    reports.append(report)
    service.attach_report(cluster.id, report.id)
    redactor = Redactor(secrets=(SECRET,), private_roots=(Path(PRIVATE),))
    context = ApiContext(
        clusters=clusters,
        agents=agents,
        tasks=tasks,
        candidates=candidates,
        records=records,
        jobs=InMemoryToolJobRepository(),
        directions=InMemoryDirectionRepository(),
        reports=reports,
        messages=FakeMessageBus(),
        artifacts=artifacts,
        cluster_service=service,
        redactor=redactor,
        now_ms=lambda: 0,
    )
    return TestClient(create_app(context=context)), {
        "cluster": cluster.id.value,
        "candidate": candidate.id.value,
        "record": record.id.value,
    }


# ---- redactor ---------------------------------------------------------------
def test_redactor_replaces_registered_secrets_and_private_roots() -> None:
    redactor = Redactor(secrets=(SECRET, "short"), private_roots=(Path(PRIVATE),))

    assert redactor.redact_text(f"{SECRET} {PRIVATE}") == f"{REDACTED} {PRIVATE_PATH}"
    assert redactor.redact_text("short") == "short"
    assert redactor.redact({"nested": [SECRET]}) == {"nested": (REDACTED,)}


# ---- redacted source/export/report -----------------------------------------
def test_source_export_and_report_are_redacted_and_acl_protected() -> None:
    client, ids = _client()
    no_human = client.get(f"/api/v1/candidates/{ids['candidate']}/source")
    source = client.get(
        f"/api/v1/candidates/{ids['candidate']}/source",
        headers={"X-Human": "true"},
    )
    no_export = client.get(f"/api/v1/export?cluster_id={ids['cluster']}")
    exported = client.get(
        f"/api/v1/export?cluster_id={ids['cluster']}",
        headers={"X-Human": "true"},
    )
    report = client.get(
        f"/api/v1/clusters/{ids['cluster']}/report/download",
        headers={"X-Human": "true"},
    )

    assert no_human.status_code == 403
    assert source.status_code == 200
    assert SECRET not in str(source.json())
    assert PRIVATE not in str(source.json())
    assert REDACTED in str(source.json())
    assert PRIVATE_PATH in str(source.json())
    assert no_export.status_code == 403
    assert exported.status_code == 200
    assert SECRET not in str(exported.json())
    assert PRIVATE not in str(exported.json())
    assert REDACTED in str(exported.json())
    assert report.status_code == 200
    assert SECRET not in report.text
    assert PRIVATE not in report.text
    assert REDACTED in report.text


# ---- download ACL -----------------------------------------------------------
def test_record_download_requires_human_or_authorized_agent() -> None:
    client, ids = _client()

    missing = client.get(f"/api/v1/records/{ids['record']}/download")
    human = client.get(
        f"/api/v1/records/{ids['record']}/download",
        headers={"X-Human": "true"},
    )

    assert missing.status_code == 403
    assert human.status_code == 200
    assert human.content == b"zip"

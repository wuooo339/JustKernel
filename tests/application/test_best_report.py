from __future__ import annotations

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.application.best_report_service import BestSelectionService, ReportService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryBestSelectionRepository,
    InMemoryBudgetLedger,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryReportRepository,
    InMemoryTestRecordRepository,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.errors import BestSelectionError
from justkernel.candidate.source import SourceRevision
from justkernel.candidate.state import SelectionState
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.report.errors import ReportError
from justkernel.report.report import ReportDirection
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    TaskId,
)
from justkernel.shared.ids import (
    TestRecordId as RecordId,
)
from justkernel.shared.principal import Principal
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import (
    TestCoverage as Coverage,
)
from justkernel.testing.state import (
    TestOutcome as Outcome,
)
from justkernel.testing.state import (
    TestRecordKind as RecordKind,
)


# ---- helpers ----------------------------------------------------------------
def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _cluster() -> Cluster:
    return Cluster(
        id=ClusterId.generate(),
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        created_at=0,
    )


def _candidate(cluster: Cluster) -> CandidateVersion:
    return CandidateVersion(
        id=CandidateId.generate(),
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        parent_id=None,
        author_agent_id=None,
        author_principal=Principal.system(),
        task_id=None,
        import_id="import-1",
        source=SourceRevision.from_files({"op_kernel/kernel.cpp": "// root"}),
        diff_artifact="artifact://diff",
        created_at=0,
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(ref="artifact://record", digest=Digest.from_text("zip"))


def _environment() -> Environment:
    return Environment(values=(("soc", "Ascend910B4"),))


def _record(candidate: CandidateVersion, **overrides: object) -> Record:
    values: dict[str, object] = {
        "id": RecordId.generate(),
        "candidate_id": candidate.id,
        "kind": RecordKind.TEST,
        "skill_ref": _skill(),
        "backend": "cann-simulation",
        "outcome": Outcome.PASS,
        "coverage": Coverage.FULL,
        "executed": True,
        "artifact": _artifact(),
        "environment": _environment(),
        "created_at": 0,
        "task_id": TaskId.generate(),
        "job_id": "job-1",
    }
    values.update(overrides)
    return Record(**values)


def _best_stack() -> tuple[
    BestSelectionService,
    InMemoryBestSelectionRepository,
    InMemoryCandidateRepository,
    InMemoryTestRecordRepository,
    Cluster,
    CandidateVersion,
    Record,
]:
    clusters = InMemoryClusterRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    selections = InMemoryBestSelectionRepository()
    service = BestSelectionService(clusters, candidates, records, selections, FakeIds())
    cluster = _cluster()
    clusters.insert(cluster)
    candidate = _candidate(cluster)
    candidates.insert(candidate)
    record = _record(candidate)
    records.append(record)
    return service, selections, candidates, records, cluster, candidate, record


def _report_stack() -> tuple[
    ReportService,
    InMemoryReportRepository,
    InMemoryCandidateRepository,
    InMemoryTestRecordRepository,
    Cluster,
    CandidateVersion,
    Record,
]:
    clusters = InMemoryClusterRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    reports = InMemoryReportRepository()
    service = ReportService(clusters, candidates, records, reports)
    cluster = _cluster()
    clusters.insert(cluster)
    candidate = _candidate(cluster)
    candidates.insert(candidate)
    record = _record(candidate)
    records.append(record)
    return service, reports, candidates, records, cluster, candidate, record


# ---- best selection ---------------------------------------------------------
def test_nominate_and_validate_best() -> None:
    service, selections, _, _, cluster, candidate, record = _best_stack()
    selection = service.nominate_best(
        cluster_id=cluster.id,
        candidate_id=candidate.id,
        policy_digest=Digest.from_text("policy"),
        nomination_record_ids=(record.id,),
        reason="best evidence",
        created_at=0,
    )

    assert selection.state is SelectionState.PENDING
    assert selections.get(selection.id) == selection

    validated = service.validate_best(
        selection_id=selection.id,
        final_task_ids=(TaskId.generate(),),
        final_record_ids=(record.id,),
    )
    assert validated.state is SelectionState.VALIDATED
    assert validated.final_record_ids == (record.id,)


def test_best_requires_full_pass_candidate_evidence() -> None:
    service, _, candidates, records, cluster, candidate, record = _best_stack()
    audit = _record(
        candidate,
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    records.append(audit)

    with pytest.raises(BestSelectionError):
        service.nominate_best(
            cluster_id=cluster.id,
            candidate_id=candidate.id,
            policy_digest=Digest.from_text("policy"),
            nomination_record_ids=(audit.id,),
            reason="bad evidence",
            created_at=0,
        )

    other = _candidate(cluster)
    candidates.insert(other)
    other_record = _record(other)
    records.append(other_record)
    with pytest.raises(BestSelectionError):
        service.nominate_best(
            cluster_id=cluster.id,
            candidate_id=candidate.id,
            policy_digest=Digest.from_text("policy"),
            nomination_record_ids=(other_record.id,),
            reason="wrong candidate evidence",
            created_at=0,
        )


def test_final_validation_requires_full_pass() -> None:
    service, _, _, records, cluster, candidate, record = _best_stack()
    audit = _record(
        candidate,
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-2",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    records.append(audit)
    selection = service.nominate_best(
        cluster_id=cluster.id,
        candidate_id=candidate.id,
        policy_digest=Digest.from_text("policy"),
        nomination_record_ids=(record.id,),
        reason="best evidence",
        created_at=0,
    )

    with pytest.raises(BestSelectionError):
        service.validate_best(
            selection_id=selection.id,
            final_task_ids=(TaskId.generate(),),
            final_record_ids=(audit.id,),
        )


# ---- report -----------------------------------------------------------------
def test_report_service_writes_report() -> None:
    service, reports, _, _, cluster, candidate, record = _report_stack()
    report = service.write_report(
        report_id="report-1",
        cluster_id=cluster.id,
        best_candidate_id=candidate.id,
        revision=1,
        directions=(
            ReportDirection(
                direction_id=DirectionId.generate(),
                objective="improve memory",
                outcome="candidate improved",
            ),
        ),
        candidate_ids=(candidate.id,),
        record_ids=(record.id,),
        failures=("first candidate failed",),
        decision="best full pass",
        created_at=0,
    )

    assert reports.get("report-1") == report
    assert report.best_candidate_id == candidate.id


def test_report_rejects_unknown_candidate() -> None:
    service, _, _, _, cluster, candidate, record = _report_stack()

    with pytest.raises(ReportError):
        service.write_report(
            report_id="report-1",
            cluster_id=cluster.id,
            best_candidate_id=CandidateId.generate(),
            revision=1,
            directions=(
                ReportDirection(
                    direction_id=DirectionId.generate(),
                    objective="objective",
                    outcome="outcome",
                ),
            ),
            candidate_ids=(candidate.id,),
            record_ids=(record.id,),
            failures=(),
            decision="invalid",
            created_at=0,
        )


# ---- budget -----------------------------------------------------------------
def test_budget_reserve_and_settle() -> None:
    ledger = InMemoryBudgetLedger(limit=10)
    cluster = ClusterId.generate()

    assert ledger.available(cluster) == 10
    assert ledger.reserve(cluster, 6, "reservation-1") is True
    assert ledger.reserve(cluster, 6, "reservation-1") is True
    assert ledger.available(cluster) == 4
    assert ledger.reserve(cluster, 5, "reservation-2") is False
    assert ledger.settle(cluster, 7, "reservation-1") is False
    assert ledger.settle(cluster, 6, "reservation-1") is True
    assert ledger.available(cluster) == 4
    assert ledger.settle(cluster, 6, "reservation-1") is True
    assert ledger.reserve(cluster, 4, "reservation-3") is True
    assert ledger.available(cluster) == 0

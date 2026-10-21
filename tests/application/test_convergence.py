from __future__ import annotations

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.application.best_report_service import BestSelectionService, ReportService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.convergence_service import ConvergenceRequest, ConvergenceService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryBestSelectionRepository,
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
from justkernel.cluster.state import ClusterPhase, ClusterState, StartMode
from justkernel.report.report import ReportDirection
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, DirectionId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.shared.principal import Principal
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- helpers ----------------------------------------------------------------
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
        source=SourceRevision.from_files({"kernel.cpp": "// root"}),
        diff_artifact="artifact://diff",
        created_at=0,
    )


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
        "artifact": ArtifactRef(ref="artifact://record", digest=Digest.from_text("zip")),
        "environment": Environment(values=(("soc", "Ascend910B4"),)),
        "created_at": 0,
        "task_id": TaskId.generate(),
        "job_id": "job-1",
    }
    values.update(overrides)
    return Record(**values)


def _stack() -> tuple[
    ConvergenceService,
    ClusterService,
    InMemoryReportRepository,
    InMemoryBestSelectionRepository,
    InMemoryTestRecordRepository,
    Cluster,
    CandidateVersion,
    Record,
    object,
]:
    clusters = InMemoryClusterRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    selections = InMemoryBestSelectionRepository()
    reports = InMemoryReportRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    best = BestSelectionService(clusters, candidates, records, selections, ids)
    report_service = ReportService(clusters, candidates, records, reports)
    convergence = ConvergenceService(cluster_service, best, report_service)
    cluster = cluster_service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    cluster_service.start_cluster(cluster.id)
    candidate = _candidate(cluster)
    candidates.insert(candidate)
    cluster_service.establish_baseline(cluster.id, candidate.id)
    record = _record(candidate)
    records.append(record)
    selection = best.nominate_best(
        cluster_id=cluster.id,
        candidate_id=candidate.id,
        policy_digest=Digest.from_text("policy"),
        nomination_record_ids=(record.id,),
        reason="best evidence",
        created_at=0,
    )
    return (
        convergence,
        cluster_service,
        reports,
        selections,
        records,
        cluster_service.get(cluster.id),
        candidate,
        record,
        selection,
    )


def _complete(
    service: ConvergenceService,
    cluster: Cluster,
    candidate: CandidateVersion,
    selection: object,
    record: Record,
    *,
    report_id: str = "report-1",
) -> object:
    return service.complete(
        ConvergenceRequest(
            cluster_id=cluster.id,
            selection_id=selection.id,
            final_task_ids=(TaskId.generate(),),
            final_record_ids=(record.id,),
            report_id=report_id,
            revision=1,
            directions=(
                ReportDirection(
                    direction_id=DirectionId.generate(),
                    objective="optimize",
                    outcome="validated best",
                ),
            ),
            candidate_ids=(candidate.id,),
            record_ids=(record.id,),
            failures=(),
            decision="complete",
            now_ms=100,
        )
    )


# ---- convergence ------------------------------------------------------------
def test_valid_final_validation_completes_cluster_with_report() -> None:
    service, clusters, reports, selections, records, cluster, candidate, record, selection = (
        _stack()
    )

    result = _complete(service, cluster, candidate, selection, record)

    assert result.cluster.state is ClusterState.COMPLETED
    assert result.cluster.phase is ClusterPhase.FINALIZING
    assert result.cluster.best_candidate_id == candidate.id
    assert result.cluster.report_id == "report-1"
    assert result.selection.state is SelectionState.VALIDATED
    assert selections.get(selection.id).state is SelectionState.VALIDATED
    assert reports.get("report-1").best_candidate_id == candidate.id
    assert clusters.get(cluster.id).state is ClusterState.COMPLETED


def test_failed_final_validation_preserves_running_cluster() -> None:
    service, clusters, reports, selections, records, cluster, candidate, record, selection = (
        _stack()
    )
    failed = _record(candidate, outcome=Outcome.FAIL)
    records.append(failed)

    with pytest.raises(BestSelectionError):
        service.complete(
            ConvergenceRequest(
                cluster_id=cluster.id,
                selection_id=selection.id,
                final_task_ids=(TaskId.generate(),),
                final_record_ids=(failed.id,),
                report_id="bad-report",
                revision=1,
                directions=(
                    ReportDirection(
                        direction_id=DirectionId.generate(),
                        objective="optimize",
                        outcome="failed",
                    ),
                ),
                candidate_ids=(candidate.id,),
                record_ids=(failed.id,),
                failures=("failed final validation",),
                decision="stop",
                now_ms=100,
            )
        )

    current = clusters.get(cluster.id)
    assert current.state is ClusterState.RUNNING
    assert current.phase is ClusterPhase.OPTIMIZING
    assert current.best_candidate_id is None
    assert current.report_id is None
    assert selections.get(selection.id).state is SelectionState.PENDING

    result = _complete(service, cluster, candidate, selection, record, report_id="report-ok")
    assert result.cluster.state is ClusterState.COMPLETED
    assert result.cluster.report_id == "report-ok"

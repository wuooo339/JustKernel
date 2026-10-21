"""Cluster convergence, best-selection application and report completion."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.application.best_report_service import BestSelectionService, ReportService
from justkernel.application.cluster_service import ClusterService
from justkernel.candidate.best import BestSelection
from justkernel.cluster.cluster import Cluster
from justkernel.report.report import ExplorationReport, ReportDirection
from justkernel.shared.ids import BestSelectionId, CandidateId, ClusterId, TaskId, TestRecordId


# ---- ConvergenceRequest -----------------------------------------------------
@dataclass(frozen=True, slots=True)
class ConvergenceRequest:
    cluster_id: ClusterId
    selection_id: BestSelectionId
    final_task_ids: tuple[TaskId, ...]
    final_record_ids: tuple[TestRecordId, ...]
    report_id: str
    revision: int
    directions: tuple[ReportDirection, ...]
    candidate_ids: tuple[CandidateId, ...]
    record_ids: tuple[TestRecordId, ...]
    failures: tuple[str, ...]
    decision: str
    now_ms: int


# ---- ConvergenceResult ------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ConvergenceResult:
    cluster: Cluster
    selection: BestSelection
    report: ExplorationReport


# ---- ConvergenceService -----------------------------------------------------
class ConvergenceService:
    def __init__(
        self,
        clusters: ClusterService,
        best: BestSelectionService,
        reports: ReportService,
    ) -> None:
        self.clusters = clusters
        self.best = best
        self.reports = reports

    def complete(self, request: ConvergenceRequest) -> ConvergenceResult:
        selection = self.best.validate_best(
            selection_id=request.selection_id,
            final_task_ids=request.final_task_ids,
            final_record_ids=request.final_record_ids,
        )
        report = self.reports.write_report(
            report_id=request.report_id,
            cluster_id=request.cluster_id,
            best_candidate_id=selection.candidate_id,
            revision=request.revision,
            directions=request.directions,
            candidate_ids=request.candidate_ids,
            record_ids=request.record_ids,
            failures=request.failures,
            decision=request.decision,
            created_at=request.now_ms,
        )
        cluster = self.clusters.converge_cluster(request.cluster_id)
        cluster = self.clusters.set_best_candidate(cluster.id, selection.candidate_id)
        cluster = self.clusters.attach_report(cluster.id, report.id)
        cluster = self.clusters.complete_cluster(cluster.id, request.now_ms)
        return ConvergenceResult(cluster, selection, report)

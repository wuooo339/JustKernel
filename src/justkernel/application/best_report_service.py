"""Application services for best selection and reports."""

from __future__ import annotations

from collections.abc import Sequence

from justkernel.application.evidence_chain import EvidenceError, EvidenceGate
from justkernel.application.ports import (
    BestSelectionRepositoryPort,
    CandidateRepositoryPort,
    ClusterRepositoryPort,
    IdFactoryPort,
    ReportRepositoryPort,
    TestRecordRepositoryPort,
)
from justkernel.candidate.best import BestSelection
from justkernel.candidate.errors import BestSelectionError
from justkernel.cluster.invariants import InvariantError, require_full_pass
from justkernel.report.errors import ReportError
from justkernel.report.report import ExplorationReport, ReportDirection
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    BestSelectionId,
    CandidateId,
    ClusterId,
    TaskId,
    TestRecordId,
)
from justkernel.testing.record import TestRecord
from justkernel.testing.state import TestCoverage, TestOutcome, TestRecordKind


# ---- BestSelectionService ---------------------------------------------------
class BestSelectionService:
    def __init__(
        self,
        clusters: ClusterRepositoryPort,
        candidates: CandidateRepositoryPort,
        records: TestRecordRepositoryPort,
        selections: BestSelectionRepositoryPort,
        ids: IdFactoryPort,
        *,
        evidence: EvidenceGate | None = None,
        profile_required: bool = False,
    ) -> None:
        self.clusters = clusters
        self.candidates = candidates
        self.records = records
        self.selections = selections
        self.ids = ids
        self.evidence = evidence
        self.profile_required = profile_required

    def nominate_best(
        self,
        *,
        cluster_id: ClusterId,
        candidate_id: CandidateId,
        policy_digest: Digest,
        nomination_record_ids: tuple[TestRecordId, ...],
        reason: str,
        created_at: int,
    ) -> BestSelection:
        cluster = self.clusters.get(cluster_id)
        candidate = self.candidates.get(candidate_id)
        if candidate.cluster_id != cluster.id:
            raise BestSelectionError("candidate belongs to another cluster")
        evidence = self._records(nomination_record_ids)
        if any(record.candidate_id != candidate.id for record in evidence):
            raise BestSelectionError("nomination evidence belongs to another candidate")
        self._require_full_pass(evidence)
        selection = BestSelection(
            id=self.ids.best_selection_id(),
            cluster_id=cluster.id,
            candidate_id=candidate.id,
            policy_digest=policy_digest,
            nomination_record_ids=nomination_record_ids,
            reason=reason,
            created_at=created_at,
        )
        self.selections.insert(selection)
        return selection

    def validate_best(
        self,
        *,
        selection_id: BestSelectionId,
        final_task_ids: tuple[TaskId, ...],
        final_record_ids: tuple[TestRecordId, ...],
    ) -> BestSelection:
        selection = self.selections.get(selection_id)
        final_records = self._records(final_record_ids)
        if any(record.candidate_id != selection.candidate_id for record in final_records):
            raise BestSelectionError("final evidence belongs to another candidate")
        self._require_full_pass(final_records)
        validated = selection.validated(final_task_ids, final_record_ids)
        self.selections.update(validated)
        return validated

    def _records(self, record_ids: Sequence[TestRecordId]) -> tuple[TestRecord, ...]:
        try:
            return tuple(self.records.get(record_id) for record_id in record_ids)
        except KeyError as error:
            raise BestSelectionError("test record does not exist") from error

    def _require_full_pass(self, records: Sequence[TestRecord]) -> None:
        try:
            if self.evidence is not None:
                for record in records:
                    self.evidence.require(record)
            require_full_pass(records)
            if self.profile_required and not self._has_profile(records):
                raise BestSelectionError("comparable PROFILE evidence is required")
        except (EvidenceError, InvariantError) as error:
            raise BestSelectionError("full PASS evidence is required") from error

    @staticmethod
    def _has_profile(records: Sequence[TestRecord]) -> bool:
        return any(
            record.kind is TestRecordKind.PROFILE
            and record.executed
            and record.outcome is TestOutcome.PASS
            and record.coverage is TestCoverage.FULL
            for record in records
        )


# ---- ReportService ----------------------------------------------------------
class ReportService:
    def __init__(
        self,
        clusters: ClusterRepositoryPort,
        candidates: CandidateRepositoryPort,
        records: TestRecordRepositoryPort,
        reports: ReportRepositoryPort,
    ) -> None:
        self.clusters = clusters
        self.candidates = candidates
        self.records = records
        self.reports = reports

    def write_report(
        self,
        *,
        report_id: str,
        cluster_id: ClusterId,
        best_candidate_id: CandidateId | None,
        revision: int,
        directions: tuple[ReportDirection, ...],
        candidate_ids: tuple[CandidateId, ...],
        record_ids: tuple[TestRecordId, ...],
        failures: tuple[str, ...],
        decision: str,
        created_at: int,
    ) -> ExplorationReport:
        cluster = self.clusters.get(cluster_id)
        for candidate_id in candidate_ids:
            candidate = self.candidates.get(candidate_id)
            if candidate.cluster_id != cluster.id:
                raise ReportError("report candidate belongs to another cluster")
        if best_candidate_id is not None and best_candidate_id not in candidate_ids:
            raise ReportError("best candidate is not in the report candidates")
        try:
            for record_id in record_ids:
                self.records.get(record_id)
        except KeyError as error:
            raise ReportError("report record does not exist") from error
        report = ExplorationReport(
            id=report_id,
            cluster_id=cluster.id,
            best_candidate_id=best_candidate_id,
            revision=revision,
            directions=directions,
            candidates=candidate_ids,
            records=record_ids,
            failures=failures,
            decision=decision,
            created_at=created_at,
        )
        self.reports.append(report)
        return report

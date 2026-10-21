"""Baseline establishment with bootstrap-attempt accounting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from justkernel.application.ports import (
    CandidateRepositoryPort,
    ClusterRepositoryPort,
    TestRecordRepositoryPort,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.state import ClusterPhase, ClusterState
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import CandidateId, ClusterId, TestRecordId
from justkernel.testing.policy import BudgetPolicy
from justkernel.testing.record import TestRecord
from justkernel.testing.state import TestRecordKind


# ---- errors -----------------------------------------------------------------
class BaselineError(JustKernelError):
    code = ErrorCode.BASELINE_INVALID


# ---- BaselineAttempt --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BaselineAttempt:
    cluster: Cluster
    accepted: bool
    attempts: int
    stopped: bool


# ---- BaselineService --------------------------------------------------------
class BaselineService:
    def __init__(
        self,
        clusters: ClusterRepositoryPort,
        candidates: CandidateRepositoryPort,
        records: TestRecordRepositoryPort,
        budget: BudgetPolicy,
    ) -> None:
        self.clusters = clusters
        self.candidates = candidates
        self.records = records
        self.max_attempts = budget.max_bootstrap_attempts
        self._attempts: dict[ClusterId, int] = {}

    def attempt(
        self,
        *,
        cluster_id: ClusterId,
        candidate_id: CandidateId,
        record_ids: tuple[TestRecordId, ...],
        now_ms: int,
    ) -> BaselineAttempt:
        cluster = self._cluster(cluster_id, now_ms)
        candidate = self._candidate(cluster, candidate_id)
        evidence = self._records(candidate, record_ids)
        attempts = self._attempts.get(cluster.id, 0) + 1
        self._attempts[cluster.id] = attempts
        if any(record.is_full_pass for record in evidence):
            cluster.establish_baseline(candidate.id)
            self._update(cluster)
            return BaselineAttempt(cluster, True, attempts, False)
        stopped = self.max_attempts is not None and attempts >= self.max_attempts
        if stopped:
            cluster.stop("baseline_not_established", now_ms)
            self._update(cluster)
        return BaselineAttempt(cluster, False, attempts, stopped)

    def _cluster(self, cluster_id: ClusterId, now_ms: int) -> Cluster:
        cluster = self.clusters.get(cluster_id)
        if cluster.state is not ClusterState.RUNNING:
            raise BaselineError("baseline requires a running cluster")
        if cluster.phase is not ClusterPhase.BOOTSTRAPPING:
            raise BaselineError("baseline can only be established during bootstrapping")
        if cluster.baseline_candidate_id is not None:
            raise BaselineError("baseline is already established")
        if now_ms < cluster.created_at:
            raise BaselineError("baseline time precedes cluster creation")
        return cluster

    def _candidate(self, cluster: Cluster, candidate_id: CandidateId) -> CandidateVersion:
        try:
            candidate = self.candidates.get(candidate_id)
        except KeyError as error:
            raise BaselineError("baseline candidate does not exist") from error
        if candidate.cluster_id != cluster.id:
            raise BaselineError("baseline candidate belongs to another cluster")
        return candidate

    def _records(
        self,
        candidate: CandidateVersion,
        record_ids: Sequence[TestRecordId],
    ) -> tuple[TestRecord, ...]:
        if not record_ids:
            raise BaselineError("baseline requires evidence")
        try:
            records = tuple(self.records.get(record_id) for record_id in record_ids)
        except KeyError as error:
            raise BaselineError("baseline evidence does not exist") from error
        if any(record.candidate_id != candidate.id for record in records):
            raise BaselineError("baseline evidence belongs to another candidate")
        if any(record.kind is not TestRecordKind.TEST for record in records):
            raise BaselineError("baseline requires TEST evidence")
        return records

    def _update(self, cluster: Cluster) -> None:
        version = self.clusters.version(cluster.id)
        self.clusters.update(cluster, expected_version=version)

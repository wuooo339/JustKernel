from __future__ import annotations

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.application.baseline_service import BaselineError, BaselineService
from justkernel.application.fakes import (
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryTestRecordRepository,
)
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.source import SourceRevision
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import ClusterPhase, ClusterState, StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, CandidateId, ClusterId, DirectionId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.shared.principal import Principal
from justkernel.testing.policy import BudgetPolicy
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


def _cluster(**overrides: object) -> Cluster:
    values: dict[str, object] = {
        "id": ClusterId.generate(),
        "operator_id": "op-1",
        "supervisor_id": AgentId.generate(),
        "operator_spec_ref": _operator_ref(),
        "start_mode": StartMode.GENERATE,
        "created_at": 0,
        "max_agents": 6,
        "state": ClusterState.RUNNING,
    }
    values.update(overrides)
    return Cluster(**values)


def _candidate(cluster: Cluster, **overrides: object) -> CandidateVersion:
    values: dict[str, object] = {
        "id": CandidateId.generate(),
        "cluster_id": cluster.id,
        "direction_id": DirectionId.generate(),
        "parent_id": None,
        "author_agent_id": None,
        "author_principal": Principal.system(),
        "task_id": None,
        "import_id": "import-1",
        "source": SourceRevision.from_files({"kernel.cpp": "// root"}),
        "diff_artifact": "artifact://diff",
        "created_at": 0,
    }
    values.update(overrides)
    return CandidateVersion(**values)


def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation-test",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
    )


def _environment() -> Environment:
    return Environment(values=(("soc", "Ascend910B4"),))


def _artifact() -> ArtifactRef:
    return ArtifactRef(ref="artifact://record", digest=Digest.from_text("zip"))


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


def _audit(candidate: CandidateVersion) -> Record:
    return _record(
        candidate,
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )


def _stack(
    *,
    max_bootstrap_attempts: int | None = 3,
) -> tuple[
    BaselineService,
    InMemoryClusterRepository,
    InMemoryCandidateRepository,
    InMemoryTestRecordRepository,
    Cluster,
    CandidateVersion,
]:
    clusters = InMemoryClusterRepository()
    candidates = InMemoryCandidateRepository()
    records = InMemoryTestRecordRepository()
    cluster = _cluster()
    clusters.insert(cluster)
    candidate = _candidate(cluster)
    candidates.insert(candidate)
    budget = BudgetPolicy(
        max_duration_s=60,
        max_bootstrap_attempts=max_bootstrap_attempts,
    )
    service = BaselineService(clusters, candidates, records, budget)
    return service, clusters, candidates, records, cluster, candidate


def _attempt(
    service: BaselineService,
    cluster: Cluster,
    candidate: CandidateVersion,
    records: tuple[Record, ...],
    *,
    now_ms: int = 10,
) -> object:
    return service.attempt(
        cluster_id=cluster.id,
        candidate_id=candidate.id,
        record_ids=tuple(record.id for record in records),
        now_ms=now_ms,
    )


# ---- baseline ---------------------------------------------------------------
def test_full_pass_establishes_baseline() -> None:
    service, clusters, _, records, cluster, candidate = _stack()
    record = _record(candidate)
    records.append(record)

    result = _attempt(service, cluster, candidate, (record,))

    assert result.accepted is True
    assert result.attempts == 1
    assert result.cluster.phase is ClusterPhase.OPTIMIZING
    assert result.cluster.baseline_candidate_id == candidate.id
    assert clusters.get(cluster.id).baseline_candidate_id == candidate.id


def test_non_full_pass_does_not_establish_baseline() -> None:
    service, _, _, records, cluster, candidate = _stack()
    record = _record(candidate, outcome=Outcome.FAIL)
    audit = _audit(candidate)
    records.append(record)
    records.append(audit)

    result = _attempt(service, cluster, candidate, (record, audit))

    assert result.accepted is False
    assert result.attempts == 1
    assert result.stopped is False
    assert result.cluster.baseline_candidate_id is None
    assert result.cluster.phase is ClusterPhase.BOOTSTRAPPING


def test_bootstrap_budget_exhaustion_stops_cluster() -> None:
    service, clusters, _, records, cluster, candidate = _stack(max_bootstrap_attempts=2)
    failed = _record(candidate, outcome=Outcome.FAIL)
    records.append(failed)

    first = _attempt(service, cluster, candidate, (failed,))
    second = _attempt(service, cluster, candidate, (failed,), now_ms=20)

    assert first.accepted is False
    assert first.attempts == 1
    assert first.stopped is False
    assert second.accepted is False
    assert second.attempts == 2
    assert second.stopped is True
    assert second.cluster.state is ClusterState.STOPPED
    assert second.cluster.terminal_reason == "baseline_not_established"
    assert second.cluster.baseline_candidate_id is None
    assert clusters.get(cluster.id).state is ClusterState.STOPPED


def test_success_at_attempt_limit_still_establishes_baseline() -> None:
    service, _, _, records, cluster, candidate = _stack(max_bootstrap_attempts=1)
    record = _record(candidate)
    records.append(record)

    result = _attempt(service, cluster, candidate, (record,))

    assert result.accepted is True
    assert result.stopped is False
    assert result.cluster.phase is ClusterPhase.OPTIMIZING
    assert result.cluster.baseline_candidate_id == candidate.id


def test_foreign_candidate_evidence_is_rejected() -> None:
    service, _, candidates, records, cluster, candidate = _stack()
    other_cluster = _cluster()
    foreign = _candidate(other_cluster)
    candidates.insert(foreign)
    record = _record(foreign)
    records.append(record)

    with pytest.raises(BaselineError):
        _attempt(service, cluster, foreign, (record,))


def test_second_baseline_attempt_is_rejected() -> None:
    service, _, _, records, cluster, candidate = _stack()
    record = _record(candidate)
    records.append(record)
    _attempt(service, cluster, candidate, (record,))

    with pytest.raises(BaselineError):
        _attempt(service, cluster, candidate, (record,), now_ms=20)

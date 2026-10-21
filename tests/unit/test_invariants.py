from __future__ import annotations

import pytest

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.candidate.best import BestSelection
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.source import SourceRevision
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.invariants import (
    InvariantError,
    require_full_pass,
    validate_best_selection,
    validate_candidate_evidence,
    validate_cluster_agents,
    validate_lease_uniqueness,
    validate_task_assignment,
)
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    BestSelectionId,
    CandidateId,
    ClusterId,
    DirectionId,
    LeaseId,
    TaskId,
)
from justkernel.shared.ids import (
    TestRecordId as RecordId,
)
from justkernel.shared.principal import Principal
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.lease import DeviceId, HardwareLease
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
        operator_id="ConfusionMulGrad",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _skill() -> SkillRef:
    return SkillRef(
        name="optimizer",
        version="1",
        source_path="/skills/base/optimizer",
        digest=Digest.from_text("skill"),
    )


def _cluster(**overrides: object) -> Cluster:
    values: dict[str, object] = {
        "id": ClusterId.generate(),
        "operator_id": "ConfusionMulGrad",
        "supervisor_id": AgentId.generate(),
        "operator_spec_ref": _operator_ref(),
        "start_mode": StartMode.GENERATE,
        "created_at": 0,
        "max_agents": 6,
    }
    values.update(overrides)
    return Cluster(**values)


def _agent(
    cluster: Cluster,
    role: Role,
    *,
    mentor_id: AgentId | None = None,
    state: AgentState = AgentState.IDLE,
    **overrides: object,
) -> AgentInstance:
    values: dict[str, object] = {
        "id": AgentId.generate(),
        "cluster_id": cluster.id,
        "role": role,
        "mentor_id": mentor_id,
        "model_profile": "model-1",
        "skills": (_skill(),),
        "created_at": 0,
        "state": state,
    }
    values.update(overrides)
    return AgentInstance(**values)


def _task(
    cluster: Cluster,
    worker: AgentInstance,
    mentor: AgentInstance,
    kind: TaskKind = TaskKind.OPTIMIZE,
    **overrides: object,
) -> Task:
    values: dict[str, object] = {
        "id": TaskId.generate(),
        "cluster_id": cluster.id,
        "mentor_id": mentor.id,
        "worker_id": worker.id,
        "kind": kind,
        "direction_id": DirectionId.generate(),
        "operator_spec_ref": _operator_ref(),
        "context_ref": "artifact://context",
        "context_digest": Digest.from_text("context"),
        "budget_ref": "budget-1",
        "objective": "exercise candidate",
        "created_at": 0,
    }
    if kind is not TaskKind.GENERATE:
        values["candidate_id"] = CandidateId.generate()
    if kind in (TaskKind.TEST, TaskKind.PROFILE):
        values["skill_ref"] = _skill()
    values.update(overrides)
    return Task(**values)


def _candidate(cluster: Cluster) -> CandidateVersion:
    agent = AgentId.generate()
    return CandidateVersion(
        id=CandidateId.generate(),
        cluster_id=cluster.id,
        direction_id=DirectionId.generate(),
        parent_id=None,
        author_agent_id=agent,
        author_principal=Principal.agent(agent),
        task_id=TaskId.generate(),
        import_id=None,
        source=SourceRevision.from_files({"op_kernel/kernel.cpp": "// kernel"}),
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


def _selection(
    candidate: CandidateVersion,
    record: Record,
    **overrides: object,
) -> BestSelection:
    values: dict[str, object] = {
        "id": BestSelectionId.generate(),
        "cluster_id": candidate.cluster_id,
        "candidate_id": candidate.id,
        "policy_digest": Digest.from_text("policy"),
        "nomination_record_ids": (record.id,),
        "reason": "best evidence",
        "created_at": 0,
    }
    values.update(overrides)
    return BestSelection(**values)


def _lease(device: str = "npu:0") -> HardwareLease:
    lease = HardwareLease(
        id=LeaseId.generate(),
        device_id=DeviceId(device),
        task_id=TaskId.generate(),
        owner_agent_id=AgentId.generate(),
    )
    lease.acquire(0, 10)
    return lease


# ---- cluster/agent invariants ----------------------------------------------
def test_cluster_agents_invariant() -> None:
    cluster = _cluster()
    supervisor = _agent(cluster, Role.SUPERVISOR, id=cluster.supervisor_id)
    mentor = _agent(cluster, Role.MENTOR)
    worker = _agent(cluster, Role.OPTIMIZER, mentor_id=mentor.id)

    validate_cluster_agents(cluster, (supervisor, mentor, worker))


def test_cluster_requires_exactly_one_supervisor() -> None:
    cluster = _cluster()
    mentor = _agent(cluster, Role.MENTOR)
    with pytest.raises(InvariantError):
        validate_cluster_agents(cluster, (mentor,))

    supervisor = _agent(cluster, Role.SUPERVISOR, id=cluster.supervisor_id)
    second = _agent(cluster, Role.SUPERVISOR)
    with pytest.raises(InvariantError):
        validate_cluster_agents(cluster, (supervisor, second, mentor))


def test_active_agent_limit() -> None:
    cluster = _cluster(max_agents=6)
    supervisor = _agent(cluster, Role.SUPERVISOR, id=cluster.supervisor_id)
    mentor = _agent(cluster, Role.MENTOR)
    workers = [_agent(cluster, Role.OPTIMIZER, mentor_id=mentor.id) for _ in range(5)]

    with pytest.raises(InvariantError):
        validate_cluster_agents(cluster, (supervisor, mentor, *workers))


def test_worker_mentor_must_exist_and_be_a_mentor() -> None:
    cluster = _cluster()
    supervisor = _agent(cluster, Role.SUPERVISOR, id=cluster.supervisor_id)
    missing_mentor = _agent(cluster, Role.OPTIMIZER, mentor_id=AgentId.generate())

    with pytest.raises(InvariantError):
        validate_cluster_agents(cluster, (supervisor, missing_mentor))

    wrong_role = _agent(cluster, Role.OPTIMIZER, mentor_id=supervisor.id)
    with pytest.raises(InvariantError):
        validate_cluster_agents(cluster, (supervisor, wrong_role))


def test_agent_from_another_cluster_is_rejected() -> None:
    cluster = _cluster()
    supervisor = _agent(cluster, Role.SUPERVISOR, id=cluster.supervisor_id)
    mentor = _agent(cluster, Role.MENTOR)
    foreign = _agent(_cluster(), Role.MENTOR)

    with pytest.raises(InvariantError):
        validate_cluster_agents(cluster, (supervisor, mentor, foreign))


# ---- task assignment --------------------------------------------------------
def test_task_assignment_invariant() -> None:
    cluster = _cluster()
    supervisor = _agent(cluster, Role.SUPERVISOR, id=cluster.supervisor_id)
    mentor = _agent(cluster, Role.MENTOR)
    optimizer = _agent(cluster, Role.OPTIMIZER, mentor_id=mentor.id)
    task = _task(cluster, optimizer, mentor)

    validate_task_assignment(task, optimizer, mentor)
    validate_cluster_agents(cluster, (supervisor, mentor, optimizer))

    tester = _agent(cluster, Role.TESTER, mentor_id=mentor.id)
    wrong_role = _task(cluster, tester, mentor, TaskKind.OPTIMIZE)
    with pytest.raises(InvariantError):
        validate_task_assignment(wrong_role, tester, mentor)

    closed = _agent(
        cluster,
        Role.OPTIMIZER,
        mentor_id=mentor.id,
        state=AgentState.CLOSED,
        closed_at=10,
    )
    with pytest.raises(InvariantError):
        validate_task_assignment(_task(cluster, closed, mentor), closed, mentor)


# ---- evidence and best ------------------------------------------------------
def test_candidate_evidence_and_full_pass() -> None:
    cluster = _cluster()
    candidate = _candidate(cluster)
    record = _record(candidate)

    validate_candidate_evidence(candidate, (record,))
    require_full_pass((record,))

    with pytest.raises(InvariantError):
        validate_candidate_evidence(candidate, ())

    audit = _record(
        candidate,
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    with pytest.raises(InvariantError):
        require_full_pass((audit,))


def test_best_selection_invariant() -> None:
    cluster = _cluster()
    candidate = _candidate(cluster)
    record = _record(candidate)
    selection = _selection(candidate, record)

    validate_best_selection(selection, (candidate.id,), (record,))

    unknown = _selection(candidate, record, candidate_id=CandidateId.generate())
    with pytest.raises(InvariantError):
        validate_best_selection(unknown, (candidate.id,), (record,))

    validated = selection.validated((TaskId.generate(),), (record.id,))
    validate_best_selection(validated, (candidate.id,), (record,))

    audit = _record(
        candidate,
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    invalid = selection.validated((TaskId.generate(),), (audit.id,))
    with pytest.raises(InvariantError):
        validate_best_selection(invalid, (candidate.id,), (audit,))


# ---- lease uniqueness -------------------------------------------------------
def test_lease_uniqueness() -> None:
    first = _lease("npu:0")
    second = _lease("npu:0")

    with pytest.raises(InvariantError):
        validate_lease_uniqueness((first, second))

    second.release(5)
    validate_lease_uniqueness((first, second))

    third = _lease("npu:1")
    validate_lease_uniqueness((first, third))

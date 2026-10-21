"""Cross-aggregate invariants."""

from __future__ import annotations

from collections.abc import Sequence

from justkernel.agent.agent import AgentInstance
from justkernel.agent.state import WORKER_ROLES, AgentState, Role
from justkernel.candidate.best import BestSelection
from justkernel.candidate.candidate import CandidateVersion
from justkernel.candidate.state import SelectionState
from justkernel.cluster.cluster import Cluster
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import CandidateId
from justkernel.task.state import TaskKind
from justkernel.task.task import Task
from justkernel.testing.lease import HardwareLease
from justkernel.testing.record import TestRecord
from justkernel.testing.state import LeaseState

TASK_ROLE = {
    TaskKind.GENERATE: Role.OPTIMIZER,
    TaskKind.OPTIMIZE: Role.OPTIMIZER,
    TaskKind.TEST: Role.TESTER,
    TaskKind.PROFILE: Role.PROFILER,
}


# ---- InvariantError ---------------------------------------------------------
class InvariantError(JustKernelError):
    code = ErrorCode.INVARIANT_VIOLATION


# ---- _require ---------------------------------------------------------------
def _require(condition: object, message: str) -> None:
    if not condition:
        raise InvariantError(message)


# ---- validate_cluster_agents ------------------------------------------------
def validate_cluster_agents(cluster: Cluster, agents: Sequence[AgentInstance]) -> None:
    members = tuple(agents)
    _require(len({agent.id for agent in members}) == len(members), "duplicate agent id")
    _require(
        all(agent.cluster_id == cluster.id for agent in members),
        "agent belongs to another cluster",
    )
    active = [agent for agent in members if agent.state is not AgentState.CLOSED]
    _require(len(active) <= cluster.max_agents, "active agents exceed max_agents")
    supervisors = [agent for agent in active if agent.role is Role.SUPERVISOR]
    _require(len(supervisors) == 1, "cluster requires exactly one active supervisor")
    _require(supervisors[0].id == cluster.supervisor_id, "supervisor id mismatch")

    by_id = {agent.id: agent for agent in members}
    for agent in members:
        if agent.role not in WORKER_ROLES:
            continue
        mentor = by_id.get(agent.mentor_id) if agent.mentor_id else None
        if mentor is None:
            raise InvariantError("worker mentor does not exist")
        _require(mentor.role is Role.MENTOR, "worker mentor is not a mentor")
        _require(mentor.cluster_id == cluster.id, "worker mentor is in another cluster")


# ---- validate_task_assignment ----------------------------------------------
def validate_task_assignment(task: Task, worker: AgentInstance, mentor: AgentInstance) -> None:
    _require(
        task.cluster_id == worker.cluster_id == mentor.cluster_id,
        "task/worker/mentor cluster mismatch",
    )
    _require(task.worker_id == worker.id, "task worker id mismatch")
    _require(task.mentor_id == mentor.id, "task mentor id mismatch")
    _require(worker.mentor_id == mentor.id, "worker is not assigned to this mentor")
    _require(mentor.role is Role.MENTOR, "task owner is not a mentor")
    _require(worker.state is not AgentState.CLOSED, "closed worker cannot receive a task")
    _require(worker.role is TASK_ROLE[task.kind], "task kind does not match worker role")
    if worker.current_task_id is not None:
        _require(worker.current_task_id == task.id, "worker is already running another task")


# ---- evidence ---------------------------------------------------------------
def validate_candidate_evidence(candidate: CandidateVersion, records: Sequence[TestRecord]) -> None:
    evidence = tuple(records)
    _require(evidence, "candidate requires at least one TestRecord")
    _require(len({record.id for record in evidence}) == len(evidence), "duplicate test record")
    _require(
        all(record.candidate_id == candidate.id for record in evidence),
        "test record belongs to another candidate",
    )


def require_full_pass(records: Sequence[TestRecord]) -> None:
    _require(any(record.is_full_pass for record in records), "full PASS evidence required")


# ---- best selection ---------------------------------------------------------
def validate_best_selection(
    selection: BestSelection,
    candidate_ids: Sequence[CandidateId],
    records: Sequence[TestRecord],
) -> None:
    _require(selection.candidate_id in candidate_ids, "best candidate does not exist")
    by_id = {record.id: record for record in records}
    _require(
        all(record_id in by_id for record_id in selection.nomination_record_ids),
        "nomination record does not exist",
    )
    if selection.state is SelectionState.VALIDATED:
        _require(selection.final_record_ids, "validated selection requires final records")
        _require(
            all(record_id in by_id for record_id in selection.final_record_ids),
            "final record does not exist",
        )
        _require(
            all(by_id[record_id].is_full_pass for record_id in selection.final_record_ids),
            "validated selection requires full PASS final records",
        )


# ---- lease uniqueness -------------------------------------------------------
def validate_lease_uniqueness(leases: Sequence[HardwareLease]) -> None:
    devices = [lease.device_id.value for lease in leases if lease.state is LeaseState.LEASED]
    _require(len(set(devices)) == len(devices), "device has multiple active leases")

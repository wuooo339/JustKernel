"""Shared HTTP route conversions and object ACL checks."""

from __future__ import annotations

from fastapi import Request

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.direction import Direction
from justkernel.comm.errors import AccessDeniedError
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.dtos import (
    AgentView,
    CandidateView,
    ClusterView,
    DirectionView,
    ReportView,
    SkillView,
    TaskView,
    TestRecordView,
)
from justkernel.platform.http.errors import NotFoundError
from justkernel.report.report import ExplorationReport
from justkernel.shared.ids import AgentId, CandidateId, ClusterId, TaskId, TestRecordId
from justkernel.task.task import Task
from justkernel.testing.record import TestRecord


# ---- lookups ----------------------------------------------------------------
def cluster(ctx: ApiContext, cluster_id: str) -> Cluster:
    try:
        return ctx.clusters.get(ClusterId(cluster_id))
    except (KeyError, ValueError) as error:
        raise NotFoundError(f"cluster not found: {cluster_id}") from error


def agent(ctx: ApiContext, agent_id: str) -> AgentInstance:
    try:
        return ctx.agents.get(AgentId(agent_id))
    except (KeyError, ValueError) as error:
        raise NotFoundError(f"agent not found: {agent_id}") from error


def task(ctx: ApiContext, task_id: str) -> Task:
    try:
        return ctx.tasks.get(TaskId(task_id))
    except (KeyError, ValueError) as error:
        raise NotFoundError(f"task not found: {task_id}") from error


def candidate(ctx: ApiContext, candidate_id: str) -> CandidateVersion:
    try:
        return ctx.candidates.get(CandidateId(candidate_id))
    except (KeyError, ValueError) as error:
        raise NotFoundError(f"candidate not found: {candidate_id}") from error


def record(ctx: ApiContext, record_id: str) -> TestRecord:
    try:
        return ctx.records.get(TestRecordId(record_id))
    except (KeyError, ValueError) as error:
        raise NotFoundError(f"record not found: {record_id}") from error


def report(ctx: ApiContext, cluster_obj: Cluster) -> ExplorationReport:
    if cluster_obj.report_id is None:
        raise NotFoundError("cluster has no report")
    try:
        return ctx.reports.get(cluster_obj.report_id)
    except KeyError as error:
        raise NotFoundError("report not found") from error


# ---- ACL --------------------------------------------------------------------
def caller_agent(request: Request) -> AgentId:
    raw = request.headers.get("X-Agent-Id")
    if not raw:
        raise AccessDeniedError("X-Agent-Id is required")
    try:
        return AgentId(raw)
    except ValueError as error:
        raise AccessDeniedError("invalid X-Agent-Id") from error


def require_task_reader(task_obj: Task, request: Request) -> AgentId:
    caller = caller_agent(request)
    if caller not in (task_obj.worker_id, task_obj.mentor_id):
        raise AccessDeniedError("agent cannot read this task context")
    return caller


def require_human(request: Request) -> None:
    if request.headers.get("X-Human", "").lower() not in {"1", "true", "yes"}:
        raise AccessDeniedError("human request is required")


def require_record_download(ctx: ApiContext, record_obj: TestRecord, request: Request) -> None:
    if request.headers.get("X-Human", "").lower() in {"1", "true", "yes"}:
        return
    caller = caller_agent(request)
    if record_obj.task_id is None:
        raise AccessDeniedError("record has no task authorization")
    task_obj = ctx.tasks.get(record_obj.task_id)
    if caller not in (task_obj.worker_id, task_obj.mentor_id):
        raise AccessDeniedError("agent cannot download this record")


# ---- views ------------------------------------------------------------------
def cluster_view(ctx: ApiContext, obj: Cluster) -> ClusterView:
    active = sum(1 for item in ctx.agents.list_by_cluster(obj.id) if item.state.value != "CLOSED")
    return ClusterView(
        id=obj.id.value,
        operator_id=obj.operator_id,
        supervisor_id=obj.supervisor_id.value,
        state=obj.state.value,
        phase=obj.phase.value,
        start_mode=obj.start_mode.value,
        operator_spec_digest=obj.operator_spec_ref.digest.value,
        baseline_candidate_id=obj.baseline_candidate_id.value
        if obj.baseline_candidate_id
        else None,
        continued_from_cluster_id=(
            obj.continued_from_cluster_id.value if obj.continued_from_cluster_id else None
        ),
        max_agents=obj.max_agents,
        active_agents=active,
        best_candidate_id=obj.best_candidate_id.value if obj.best_candidate_id else None,
        report_id=obj.report_id,
        created_at=obj.created_at,
        closed_at=obj.closed_at,
    )


def skill_view(skill: SkillRef) -> SkillView:
    return SkillView(
        name=str(skill.name),
        version=str(skill.version),
        digest=str(skill.digest.value),
    )


def agent_view(obj: AgentInstance) -> AgentView:
    return AgentView(
        id=obj.id.value,
        role=obj.role.value,
        mentor_id=obj.mentor_id.value if obj.mentor_id else None,
        model_profile=obj.model_profile,
        skills=tuple(skill_view(skill) for skill in obj.skills),
        state=obj.state.value,
        current_task_id=obj.current_task_id.value if obj.current_task_id else None,
        created_at=obj.created_at,
        closed_at=obj.closed_at,
    )


def direction_view(obj: Direction) -> DirectionView:
    return DirectionView(
        id=obj.id.value,
        mentor_id=obj.mentor_id.value,
        objective=obj.objective,
        constraints=obj.constraints,
        state=obj.state.value,
        summary=obj.summary,
        created_at=obj.created_at,
        closed_at=obj.closed_at,
    )


def candidate_view(ctx: ApiContext, obj: CandidateVersion) -> CandidateView:
    return CandidateView(
        id=obj.id.value,
        parent_id=obj.parent_id.value if obj.parent_id else None,
        direction_id=obj.direction_id.value,
        author_agent_id=obj.author_agent_id.value if obj.author_agent_id else None,
        author_principal=str(obj.author_principal),
        evaluation={},
        source_digest=obj.source.digest.value,
        metrics={},
        record_count=len(ctx.records.list_by_candidate(obj.id)),
        created_at=obj.created_at,
    )


def task_view(obj: Task) -> TaskView:
    return TaskView(
        id=obj.id.value,
        cluster_id=obj.cluster_id.value,
        mentor_id=obj.mentor_id.value,
        worker_id=obj.worker_id.value,
        kind=obj.kind.value,
        direction_id=obj.direction_id.value,
        candidate_id=obj.candidate_id.value if obj.candidate_id else None,
        state=obj.state.value,
        objective=obj.objective,
        result_ref=obj.result_ref,
        retry_of_task_id=obj.retry_of_task_id.value if obj.retry_of_task_id else None,
        created_at=obj.created_at,
        finished_at=obj.finished_at,
    )


def record_view(ctx: ApiContext, obj: TestRecord) -> TestRecordView:
    cluster_obj = ctx.clusters.get(ctx.candidates.get(obj.candidate_id).cluster_id)
    return TestRecordView(
        id=obj.id.value,
        candidate_id=obj.candidate_id.value,
        kind=obj.kind.value,
        skill=skill_view(obj.skill_ref),
        backend=obj.backend,
        outcome=obj.outcome.value,
        executed=obj.executed,
        coverage=obj.coverage.value,
        operator_spec_digest=cluster_obj.operator_spec_ref.digest.value,
        case_pack_digest="",
        evaluation_policy_digest="",
        metrics={},
        environment=dict(obj.environment.values),
        artifact_digest=obj.artifact.digest.value,
        created_at=obj.created_at,
    )


def report_view(obj: ExplorationReport) -> ReportView:
    return ReportView(
        id=obj.id,
        cluster_id=obj.cluster_id.value,
        best_candidate_id=obj.best_candidate_id.value if obj.best_candidate_id else None,
        revision=obj.revision,
        directions=tuple(
            {
                "direction_id": item.direction_id.value,
                "objective": item.objective,
                "outcome": item.outcome,
            }
            for item in obj.directions
        ),
        candidates=tuple(item.value for item in obj.candidates),
        records=tuple(item.value for item in obj.records),
        failures=obj.failures,
        decision=obj.decision,
        created_at=obj.created_at,
    )

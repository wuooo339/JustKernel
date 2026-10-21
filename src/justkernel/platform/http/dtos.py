"""Read-model DTOs exposed by the HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillView:
    name: str
    version: str
    digest: str


@dataclass(frozen=True, slots=True)
class ClusterView:
    id: str
    operator_id: str
    supervisor_id: str
    state: str
    phase: str
    start_mode: str
    operator_spec_digest: str
    baseline_candidate_id: str | None
    continued_from_cluster_id: str | None
    max_agents: int
    active_agents: int
    best_candidate_id: str | None
    report_id: str | None
    created_at: int
    closed_at: int | None


@dataclass(frozen=True, slots=True)
class AgentView:
    id: str
    role: str
    mentor_id: str | None
    model_profile: str
    skills: tuple[SkillView, ...]
    state: str
    current_task_id: str | None
    created_at: int
    closed_at: int | None


@dataclass(frozen=True, slots=True)
class CandidateView:
    id: str
    parent_id: str | None
    direction_id: str
    author_agent_id: str | None
    author_principal: str
    evaluation: dict[str, object]
    source_digest: str
    metrics: dict[str, object]
    record_count: int
    created_at: int


@dataclass(frozen=True, slots=True)
class TestRecordView:
    id: str
    candidate_id: str
    kind: str
    skill: SkillView
    backend: str
    outcome: str
    executed: bool
    coverage: str
    operator_spec_digest: str
    case_pack_digest: str
    evaluation_policy_digest: str
    metrics: dict[str, object]
    environment: dict[str, str]
    artifact_digest: str
    created_at: int


@dataclass(frozen=True, slots=True)
class BoardPostView:
    id: str
    seq: int
    board: str
    topic: str
    author_agent_id: str
    payload: dict[str, object]
    created_at: int


@dataclass(frozen=True, slots=True)
class QueueView:
    devices: tuple[dict[str, object], ...]
    queued: tuple[dict[str, object], ...]
    leased: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class DirectionView:
    id: str
    mentor_id: str
    objective: str
    constraints: tuple[str, ...]
    state: str
    summary: str | None
    created_at: int
    closed_at: int | None


@dataclass(frozen=True, slots=True)
class TaskView:
    id: str
    cluster_id: str
    mentor_id: str
    worker_id: str
    kind: str
    direction_id: str
    candidate_id: str | None
    state: str
    objective: str
    result_ref: str | None
    retry_of_task_id: str | None
    created_at: int
    finished_at: int | None


@dataclass(frozen=True, slots=True)
class ToolJobReadView:
    job_id: str
    task_id: str
    state: str
    record_id: str | None
    error: str | None
    queue_position: int | None


@dataclass(frozen=True, slots=True)
class MessageView:
    id: str
    seq: int
    channel: str
    type: str
    sender: str
    recipient: str | None
    payload: dict[str, object]
    created_at: int


@dataclass(frozen=True, slots=True)
class ReportView:
    id: str
    cluster_id: str
    best_candidate_id: str | None
    revision: int
    directions: tuple[dict[str, object], ...]
    candidates: tuple[str, ...]
    records: tuple[str, ...]
    failures: tuple[str, ...]
    decision: str
    created_at: int


@dataclass(frozen=True, slots=True)
class EventView:
    seq: int
    id: str
    cluster_id: str
    type: str
    occurred_at: int
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class EventPage:
    events: tuple[EventView, ...]
    next_after: int

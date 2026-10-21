"""Deterministic in-memory fakes for application tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from justkernel.agent.agent import AgentInstance
from justkernel.agent.model_profile import ModelProfile
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import Role
from justkernel.application.ports import IdFactoryPort
from justkernel.candidate.best import BestSelection
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.cluster import Cluster
from justkernel.comm.channels import Channel
from justkernel.comm.message import Message
from justkernel.report.report import ExplorationReport
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    BestSelectionId,
    CandidateId,
    ClusterId,
    DirectionId,
    EventId,
    LeaseId,
    MessageId,
    TaskId,
    TestRecordId,
)
from justkernel.task.task import Task
from justkernel.testing.job import ToolJob
from justkernel.testing.record import TestRecord


# ---- FakeIds ----------------------------------------------------------------
class FakeIds:
    def __init__(self) -> None:
        self._counter = 0

    def _next(self) -> str:
        self._counter += 1
        return f"{self._counter:032x}"

    def cluster_id(self) -> ClusterId:
        return ClusterId(self._next())

    def agent_id(self) -> AgentId:
        return AgentId(self._next())

    def direction_id(self) -> DirectionId:
        return DirectionId(self._next())

    def task_id(self) -> TaskId:
        return TaskId(self._next())

    def candidate_id(self) -> CandidateId:
        return CandidateId(self._next())

    def test_record_id(self) -> TestRecordId:
        return TestRecordId(self._next())

    def message_id(self) -> MessageId:
        return MessageId(self._next())

    def lease_id(self) -> LeaseId:
        return LeaseId(self._next())

    def best_selection_id(self) -> BestSelectionId:
        return BestSelectionId(self._next())

    def event_id(self) -> EventId:
        return EventId(self._next())


# ---- in-memory repositories -------------------------------------------------
class InMemoryClusterRepository:
    def __init__(self) -> None:
        self._items: dict[ClusterId, Cluster] = {}
        self._versions: dict[ClusterId, int] = {}

    def insert(self, cluster: Cluster) -> None:
        if cluster.id in self._items:
            raise ValueError(f"cluster already exists: {cluster.id}")
        self._items[cluster.id] = cluster
        self._versions[cluster.id] = 0

    def update(self, cluster: Cluster, expected_version: int) -> int:
        if self._versions.get(cluster.id) != expected_version:
            raise ValueError(f"cluster version conflict: {cluster.id}")
        self._items[cluster.id] = cluster
        self._versions[cluster.id] = expected_version + 1
        return expected_version + 1

    def get(self, cluster_id: ClusterId) -> Cluster:
        return self._items[cluster_id]

    def version(self, cluster_id: ClusterId) -> int:
        return self._versions[cluster_id]


class InMemoryAgentRepository:
    def __init__(self) -> None:
        self._items: dict[AgentId, AgentInstance] = {}
        self._versions: dict[AgentId, int] = {}

    def insert(self, agent: AgentInstance) -> None:
        if agent.id in self._items:
            raise ValueError(f"agent already exists: {agent.id}")
        self._items[agent.id] = agent
        self._versions[agent.id] = 0

    def update(self, agent: AgentInstance, expected_version: int) -> int:
        if self._versions.get(agent.id) != expected_version:
            raise ValueError(f"agent version conflict: {agent.id}")
        self._items[agent.id] = agent
        self._versions[agent.id] = expected_version + 1
        return expected_version + 1

    def get(self, agent_id: AgentId) -> AgentInstance:
        return self._items[agent_id]

    def version(self, agent_id: AgentId) -> int:
        return self._versions[agent_id]

    def list_by_cluster(self, cluster_id: ClusterId) -> tuple[AgentInstance, ...]:
        return tuple(agent for agent in self._items.values() if agent.cluster_id == cluster_id)


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._items: dict[TaskId, Task] = {}
        self._versions: dict[TaskId, int] = {}

    def insert(self, task: Task) -> None:
        if task.id in self._items:
            raise ValueError(f"task already exists: {task.id}")
        self._items[task.id] = task
        self._versions[task.id] = 0

    def update(self, task: Task, expected_version: int) -> int:
        if self._versions.get(task.id) != expected_version:
            raise ValueError(f"task version conflict: {task.id}")
        self._items[task.id] = task
        self._versions[task.id] = expected_version + 1
        return expected_version + 1

    def get(self, task_id: TaskId) -> Task:
        return self._items[task_id]

    def version(self, task_id: TaskId) -> int:
        return self._versions[task_id]


class InMemoryModelProfileRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, ModelProfile] = {}

    def add(self, profile: ModelProfile) -> None:
        if profile.name in self._profiles:
            raise ValueError(f"model profile already exists: {profile.name}")
        self._profiles[profile.name] = profile

    def get(self, profile_name: str) -> ModelProfile:
        return self._profiles[profile_name]

    def list(self) -> tuple[ModelProfile, ...]:
        return tuple(self._profiles.values())


class InMemoryCandidateRepository:
    def __init__(self) -> None:
        self._items: dict[CandidateId, CandidateVersion] = {}

    def insert(self, candidate: CandidateVersion) -> None:
        if candidate.id in self._items:
            raise ValueError(f"candidate already exists: {candidate.id}")
        self._items[candidate.id] = candidate

    def get(self, candidate_id: CandidateId) -> CandidateVersion:
        return self._items[candidate_id]

    def list_by_cluster(self, cluster_id: ClusterId) -> tuple[CandidateVersion, ...]:
        return tuple(
            candidate for candidate in self._items.values() if candidate.cluster_id == cluster_id
        )


class InMemoryTestRecordRepository:
    def __init__(self) -> None:
        self._items: dict[TestRecordId, TestRecord] = {}
        self._by_task: dict[TaskId, TestRecordId] = {}

    def append(self, record: TestRecord) -> None:
        if record.id in self._items:
            raise ValueError(f"record already exists: {record.id}")
        self._items[record.id] = record
        if record.task_id is not None:
            self._by_task[record.task_id] = record.id

    def get(self, record_id: TestRecordId) -> TestRecord:
        return self._items[record_id]

    def get_by_task(self, task_id: TaskId) -> TestRecord | None:
        record_id = self._by_task.get(task_id)
        return self._items[record_id] if record_id is not None else None

    def list_by_candidate(self, candidate_id: CandidateId) -> tuple[TestRecord, ...]:
        return tuple(
            record for record in self._items.values() if record.candidate_id == candidate_id
        )


class InMemoryToolJobRepository:
    def __init__(self) -> None:
        self._items: dict[str, ToolJob] = {}
        self._by_task: dict[TaskId, str] = {}

    def insert(self, job: ToolJob) -> None:
        if job.id in self._items:
            raise ValueError(f"tool job already exists: {job.id}")
        self._items[job.id] = job
        self._by_task[job.task_id] = job.id

    def update(self, job: ToolJob) -> None:
        if job.id not in self._items:
            raise KeyError(job.id)
        self._items[job.id] = job

    def get(self, job_id: str) -> ToolJob:
        return self._items[job_id]

    def get_by_task(self, task_id: TaskId) -> ToolJob | None:
        job_id = self._by_task.get(task_id)
        return self._items[job_id] if job_id is not None else None


class InMemoryBestSelectionRepository:
    def __init__(self) -> None:
        self._items: dict[BestSelectionId, BestSelection] = {}

    def insert(self, selection: BestSelection) -> None:
        if selection.id in self._items:
            raise ValueError(f"selection already exists: {selection.id}")
        self._items[selection.id] = selection

    def update(self, selection: BestSelection) -> None:
        if selection.id not in self._items:
            raise KeyError(selection.id)
        self._items[selection.id] = selection

    def get(self, selection_id: BestSelectionId) -> BestSelection:
        return self._items[selection_id]


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._items: dict[str, ExplorationReport] = {}

    def append(self, report: ExplorationReport) -> None:
        if report.id in self._items:
            raise ValueError(f"report already exists: {report.id}")
        self._items[report.id] = report

    def get(self, report_id: str) -> ExplorationReport:
        return self._items[report_id]


class InMemoryBudgetLedger:
    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError("budget limit must be non-negative")
        self.limit = limit
        self._reservations: dict[str, tuple[ClusterId, int]] = {}
        self._settled: dict[str, int] = {}
        self._consumed: dict[ClusterId, int] = {}

    def reserve(self, cluster_id: ClusterId, amount: int, idempotency_key: str) -> bool:
        if amount < 0 or not idempotency_key or idempotency_key in self._settled:
            return False
        existing = self._reservations.get(idempotency_key)
        if existing is not None:
            return existing == (cluster_id, amount)
        if amount > self.available(cluster_id):
            return False
        self._reservations[idempotency_key] = (cluster_id, amount)
        return True

    def settle(self, cluster_id: ClusterId, amount: int, idempotency_key: str) -> bool:
        if self._settled.get(idempotency_key) == amount:
            return True
        reservation = self._reservations.get(idempotency_key)
        if reservation is None or reservation != (cluster_id, amount):
            return False
        del self._reservations[idempotency_key]
        self._settled[idempotency_key] = amount
        self._consumed[cluster_id] = self._consumed.get(cluster_id, 0) + amount
        return True

    def available(self, cluster_id: ClusterId) -> int:
        reserved = sum(
            amount
            for reserved_cluster, amount in self._reservations.values()
            if reserved_cluster == cluster_id
        )
        return self.limit - self._consumed.get(cluster_id, 0) - reserved


@dataclass(slots=True)
class InMemoryRepositories:
    clusters: InMemoryClusterRepository = field(default_factory=InMemoryClusterRepository)
    agents: InMemoryAgentRepository = field(default_factory=InMemoryAgentRepository)
    tasks: InMemoryTaskRepository = field(default_factory=InMemoryTaskRepository)
    candidates: InMemoryCandidateRepository = field(default_factory=InMemoryCandidateRepository)
    records: InMemoryTestRecordRepository = field(default_factory=InMemoryTestRecordRepository)
    jobs: InMemoryToolJobRepository = field(default_factory=InMemoryToolJobRepository)
    selections: InMemoryBestSelectionRepository = field(
        default_factory=InMemoryBestSelectionRepository
    )
    reports: InMemoryReportRepository = field(default_factory=InMemoryReportRepository)


# ---- message bus ------------------------------------------------------------
class FakeMessageBus:
    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._ids: set[MessageId] = set()

    def publish(self, message: Message) -> bool:
        if message.id in self._ids:
            return False
        self._ids.add(message.id)
        self._messages.append(message)
        return True

    def messages(self, channel: Channel | None = None) -> tuple[Message, ...]:
        if channel is None:
            return tuple(self._messages)
        return tuple(message for message in self._messages if message.channel == channel)


# ---- artifacts --------------------------------------------------------------
class FakeArtifactStore:
    def __init__(self) -> None:
        self._data: dict[Digest, bytes] = {}

    def put_bytes(self, data: bytes) -> Digest:
        digest = Digest.from_bytes(data)
        self._data.setdefault(digest, data)
        return digest

    def get_bytes(self, digest: Digest) -> bytes:
        return self._data[digest]

    def verify(self, digest: Digest) -> bool:
        return digest in self._data and Digest.from_bytes(self._data[digest]) == digest

    def ref_for(self, digest: Digest) -> str:
        return f"mem/{digest.value}"


# ---- runtime / tools / hardware ---------------------------------------------
class FakeAgentRuntime:
    def __init__(self, ids: IdFactoryPort | None = None) -> None:
        self.ids = ids or FakeIds()
        self.created: list[tuple[AgentId, Role, str, tuple[SkillRef, ...]]] = []
        self.turns: list[tuple[str, AgentId, str]] = []
        self.messages: list[tuple[AgentId, str]] = []
        self.closed: list[AgentId] = []
        self.cancelled: list[str] = []

    def create_agent(
        self,
        role: Role,
        model_profile: str,
        skills: tuple[SkillRef, ...],
        mentor_id: AgentId | None = None,
    ) -> AgentId:
        agent_id = self.ids.agent_id()
        self.created.append((agent_id, role, model_profile, skills))
        return agent_id

    def start_turn(self, agent_id: AgentId, input: str) -> str:
        turn_id = f"turn-{len(self.turns) + 1}"
        self.turns.append((turn_id, agent_id, input))
        return turn_id

    def send_message(self, agent_id: AgentId, message: str) -> None:
        self.messages.append((agent_id, message))

    def close_agent(self, agent_id: AgentId) -> None:
        self.closed.append(agent_id)

    def cancel_turn(self, turn_id: str) -> None:
        self.cancelled.append(turn_id)


ToolSubmission = tuple[str, TaskId, CandidateId, SkillRef, tuple[str, ...], int, str | None]


class FakeToolBackend:
    def __init__(self) -> None:
        self._counter = 0
        self.submissions: list[ToolSubmission] = []

    def _next_job(self) -> str:
        self._counter += 1
        return f"job-{self._counter}"

    def submit_test(
        self,
        *,
        task_id: TaskId,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None = None,
    ) -> str:
        self.submissions.append(
            ("TEST", task_id, candidate_id, skill_ref, case_selection, timeout_s, device)
        )
        return self._next_job()

    def submit_profile(
        self,
        *,
        task_id: TaskId,
        candidate_id: CandidateId,
        skill_ref: SkillRef,
        case_selection: tuple[str, ...],
        timeout_s: int,
        device: str | None = None,
    ) -> str:
        self.submissions.append(
            ("PROFILE", task_id, candidate_id, skill_ref, case_selection, timeout_s, device)
        )
        return self._next_job()


class FakeHardwareQueue:
    def __init__(self, ids: IdFactoryPort | None = None) -> None:
        self.ids = ids or FakeIds()
        self._leases: dict[LeaseId, str] = {}

    def acquire(self, task_id: TaskId, device: str, ttl_ms: int, now_ms: int) -> LeaseId:
        lease_id = self.ids.lease_id()
        self._leases[lease_id] = device
        return lease_id

    def release(self, lease_id: LeaseId, now_ms: int) -> None:
        del self._leases[lease_id]

    def status(self, device: str | None = None) -> tuple[LeaseId, ...]:
        return tuple(
            lease_id
            for lease_id, leased_device in self._leases.items()
            if device is None or leased_device == device
        )

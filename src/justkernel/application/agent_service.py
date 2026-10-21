"""Application service for agents, workers, and task dispatch."""

from __future__ import annotations

from justkernel.agent.agent import AgentInstance
from justkernel.agent.errors import AgentError
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import WORKER_ROLES, AgentState, Role
from justkernel.application.ports import (
    AgentRepositoryPort,
    ClusterRepositoryPort,
    IdFactoryPort,
    TaskRepositoryPort,
)
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.invariants import validate_task_assignment
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    AgentId,
    CandidateId,
    ClusterId,
    DirectionId,
    TaskId,
)
from justkernel.task.state import TaskKind
from justkernel.task.task import Task


# ---- AgentService -----------------------------------------------------------
class AgentService:
    def __init__(
        self,
        clusters: ClusterRepositoryPort,
        agents: AgentRepositoryPort,
        tasks: TaskRepositoryPort,
        ids: IdFactoryPort,
    ) -> None:
        self.clusters = clusters
        self.agents = agents
        self.tasks = tasks
        self.ids = ids

    def create_agent(
        self,
        *,
        cluster_id: ClusterId,
        role: Role,
        model_profile: str,
        skills: tuple[SkillRef, ...],
        agent_id: AgentId | None = None,
        mentor_id: AgentId | None = None,
        created_at: int = 0,
    ) -> AgentInstance:
        if role in WORKER_ROLES:
            raise AgentError("worker roles must use open_worker")
        if mentor_id is not None:
            raise AgentError("non-worker agents must not have a mentor")
        cluster = self.clusters.get(cluster_id)
        self._check_capacity(cluster)
        if role is Role.SUPERVISOR and self._active_supervisor(cluster.id):
            raise AgentError("cluster already has an active supervisor")
        agent = AgentInstance(
            id=agent_id or self.ids.agent_id(),
            cluster_id=cluster.id,
            role=role,
            mentor_id=None,
            model_profile=model_profile,
            skills=skills,
            created_at=created_at,
        )
        agent.initialize()
        self.agents.insert(agent)
        return agent

    def open_worker(
        self,
        *,
        mentor_id: AgentId,
        role: Role,
        model_profile: str,
        skills: tuple[SkillRef, ...],
        created_at: int = 0,
    ) -> AgentInstance:
        if role not in WORKER_ROLES:
            raise AgentError("open_worker requires a worker role")
        mentor = self.agents.get(mentor_id)
        if mentor.role is not Role.MENTOR or mentor.state is AgentState.CLOSED:
            raise AgentError("worker must be opened by an open mentor")
        cluster = self.clusters.get(mentor.cluster_id)
        self._check_capacity(cluster)
        worker = AgentInstance(
            id=self.ids.agent_id(),
            cluster_id=cluster.id,
            role=role,
            mentor_id=mentor.id,
            model_profile=model_profile,
            skills=skills,
            created_at=created_at,
        )
        worker.initialize()
        self.agents.insert(worker)
        return worker

    def close_worker(
        self,
        *,
        mentor_id: AgentId,
        worker_id: AgentId,
        now_ms: int,
    ) -> AgentInstance:
        mentor = self.agents.get(mentor_id)
        if mentor.role is not Role.MENTOR:
            raise AgentError("only a mentor can close a worker")
        worker = self.agents.get(worker_id)
        if worker.mentor_id != mentor_id:
            raise AgentError("worker does not belong to this mentor")
        if worker.state is AgentState.CLOSED:
            raise AgentError("worker is already closed")
        if worker.state is AgentState.RUNNING or worker.current_task_id is not None:
            raise AgentError("cancel or complete the worker task before closing")
        worker.close(now_ms)
        self._update_agent(worker)
        return worker

    def assign_task(
        self,
        *,
        mentor_id: AgentId,
        worker_id: AgentId,
        kind: TaskKind,
        direction_id: DirectionId,
        operator_spec_ref: OperatorRef,
        context_ref: str,
        context_digest: Digest,
        budget_ref: str,
        objective: str,
        constraints: tuple[str, ...] = (),
        candidate_id: CandidateId | None = None,
        skill_ref: SkillRef | None = None,
        retry_of_task_id: TaskId | None = None,
        created_at: int = 0,
    ) -> Task:
        mentor = self.agents.get(mentor_id)
        worker = self.agents.get(worker_id)
        task = self._new_task(
            mentor,
            worker,
            kind,
            direction_id,
            operator_spec_ref,
            context_ref,
            context_digest,
            budget_ref,
            objective,
            constraints,
            candidate_id,
            skill_ref,
            retry_of_task_id,
            created_at,
        )
        worker.start_task(task.id)
        self.tasks.insert(task)
        self._update_agent(worker)
        return task

    def _new_task(
        self,
        mentor: AgentInstance,
        worker: AgentInstance,
        kind: TaskKind,
        direction_id: DirectionId,
        operator_spec_ref: OperatorRef,
        context_ref: str,
        context_digest: Digest,
        budget_ref: str,
        objective: str,
        constraints: tuple[str, ...],
        candidate_id: CandidateId | None,
        skill_ref: SkillRef | None,
        retry_of_task_id: TaskId | None,
        created_at: int,
    ) -> Task:
        task = Task(
            id=self.ids.task_id(),
            cluster_id=worker.cluster_id,
            mentor_id=mentor.id,
            worker_id=worker.id,
            kind=kind,
            direction_id=direction_id,
            operator_spec_ref=operator_spec_ref,
            context_ref=context_ref,
            context_digest=context_digest,
            budget_ref=budget_ref,
            objective=objective,
            constraints=constraints,
            candidate_id=candidate_id,
            skill_ref=skill_ref,
            retry_of_task_id=retry_of_task_id,
            created_at=created_at,
        )
        validate_task_assignment(task, worker, mentor)
        task.start()
        return task

    def complete_task(
        self,
        *,
        mentor_id: AgentId,
        task_id: TaskId,
        result_ref: str,
        now_ms: int,
    ) -> Task:
        task = self.tasks.get(task_id)
        if task.mentor_id != mentor_id:
            raise AgentError("task does not belong to this mentor")
        worker = self.agents.get(task.worker_id)
        task.succeed(result_ref, now_ms)
        worker.complete_task()
        self._update_task(task)
        self._update_agent(worker)
        return task

    def _active_agents(self, cluster_id: ClusterId) -> tuple[AgentInstance, ...]:
        return tuple(
            agent
            for agent in self.agents.list_by_cluster(cluster_id)
            if agent.state is not AgentState.CLOSED
        )

    def _active_supervisor(self, cluster_id: ClusterId) -> AgentInstance | None:
        for agent in self._active_agents(cluster_id):
            if agent.role is Role.SUPERVISOR:
                return agent
        return None

    def _check_capacity(self, cluster: Cluster) -> None:
        if len(self._active_agents(cluster.id)) >= cluster.max_agents:
            raise AgentError("active agent limit reached")

    def _update_agent(self, agent: AgentInstance) -> None:
        version = self.agents.version(agent.id)
        self.agents.update(agent, expected_version=version)

    def _update_task(self, task: Task) -> None:
        version = self.tasks.version(task.id)
        self.tasks.update(task, expected_version=version)

"""Validated cluster startup with global operator reservation."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.ports import OperatorRegistryPort
from justkernel.cluster.cluster import Cluster
from justkernel.cluster.operator_spec import OperatorSpec, OperatorSpecError
from justkernel.cluster.state import ClusterState, StartMode
from justkernel.shared.ids import AgentId, ClusterId
from justkernel.testing.policy import BudgetPolicy


# ---- StartClusterRequest ----------------------------------------------------
@dataclass(frozen=True, slots=True)
class StartClusterRequest:
    operator_spec: OperatorSpec
    operator_artifact_ref: str
    start_mode: StartMode
    baseline_source_ref: str | None
    tester_skill: SkillRef
    profiler_skill: SkillRef | None
    backend: str
    devices: tuple[str, ...]
    max_agents: int
    initial_consultants: int
    initial_mentors: int
    model_profile: str
    budget: BudgetPolicy
    reservation_key: str
    journal_ref: str
    created_at: int
    supervisor_id: AgentId | None = None


# ---- StartedCluster ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class StartedCluster:
    cluster: Cluster
    supervisor: AgentInstance
    consultants: tuple[AgentInstance, ...]
    mentors: tuple[AgentInstance, ...]


# ---- ClusterStartService ----------------------------------------------------
class ClusterStartService:
    def __init__(
        self,
        clusters: ClusterService,
        agents: AgentService,
        registry: OperatorRegistryPort,
    ) -> None:
        self.clusters = clusters
        self.agents = agents
        self.registry = registry

    def start(self, request: StartClusterRequest) -> StartedCluster:
        self._validate(request)
        spec = request.operator_spec
        cluster_id = self.clusters.ids.cluster_id()
        supervisor_id = request.supervisor_id or self.agents.ids.agent_id()
        operator_ref = spec.to_ref(request.operator_artifact_ref)
        self.registry.reserve(
            operator_id=spec.operator_id,
            cluster_id=cluster_id.value,
            journal_ref=request.journal_ref,
            reservation_key=request.reservation_key,
            now_ms=request.created_at,
        )
        created: list[AgentInstance] = []
        try:
            cluster = self.clusters.create_cluster(
                operator_id=spec.operator_id,
                supervisor_id=supervisor_id,
                operator_spec_ref=operator_ref,
                start_mode=request.start_mode,
                max_agents=request.max_agents,
                created_at=request.created_at,
                cluster_id=cluster_id,
            )
            created, supervisor, consultants, mentors = self._create_roles(
                cluster, request, supervisor_id
            )
            started = self.clusters.start_cluster(cluster.id)
            return StartedCluster(started, supervisor, consultants, mentors)
        except BaseException:
            self._cleanup(cluster_id, created, request.created_at)
            raise

    def _create_roles(
        self,
        cluster: Cluster,
        request: StartClusterRequest,
        supervisor_id: AgentId,
    ) -> tuple[
        list[AgentInstance], AgentInstance, tuple[AgentInstance, ...], tuple[AgentInstance, ...]
    ]:
        supervisor = self._create_agent(cluster, request, Role.SUPERVISOR, supervisor_id)
        consultants = tuple(
            self._create_agent(cluster, request, Role.CONSULTANT)
            for _ in range(request.initial_consultants)
        )
        mentors = tuple(
            self._create_agent(cluster, request, Role.MENTOR)
            for _ in range(request.initial_mentors)
        )
        return [supervisor, *consultants, *mentors], supervisor, consultants, mentors

    def _create_agent(
        self,
        cluster: Cluster,
        request: StartClusterRequest,
        role: Role,
        agent_id: AgentId | None = None,
    ) -> AgentInstance:
        return self.agents.create_agent(
            cluster_id=cluster.id,
            role=role,
            model_profile=request.model_profile,
            skills=(),
            agent_id=agent_id,
        )

    def _cleanup(
        self,
        cluster_id: ClusterId,
        agents: list[AgentInstance],
        now_ms: int,
    ) -> None:
        for agent in agents:
            if agent.state is not AgentState.CLOSED:
                agent.close(now_ms)
                version = self.agents.agents.version(agent.id)
                self.agents.agents.update(agent, expected_version=version)
        try:
            cluster = self.clusters.get(cluster_id)
        except KeyError:
            cluster = None
        if cluster is not None and cluster.state is ClusterState.INITIALIZING:
            cluster.fail("startup failed", now_ms)
            version = self.clusters.clusters.version(cluster.id)
            self.clusters.clusters.update(cluster, expected_version=version)
        self.registry.release(cluster_id.value, "FAILED")

    def _validate(self, request: StartClusterRequest) -> None:
        spec = request.operator_spec
        if not request.operator_artifact_ref:
            raise OperatorSpecError("operator artifact ref must be non-empty")
        if not request.reservation_key or not request.journal_ref:
            raise OperatorSpecError("reservation key and journal ref must be non-empty")
        if not request.model_profile:
            raise OperatorSpecError("model profile must be non-empty")
        if not request.tester_skill.name:
            raise OperatorSpecError("tester skill is required")
        if spec.evaluation_policy.performance_target_enabled and request.profiler_skill is None:
            raise OperatorSpecError("profiler skill is required for a performance target")
        if request.backend not in spec.evaluation_policy.allowed_backends:
            raise OperatorSpecError("backend is not allowed by the evaluation policy")
        if request.start_mode is StartMode.IMPORT and not request.baseline_source_ref:
            raise OperatorSpecError("IMPORT requires a baseline source ref")
        if request.max_agents < 6:
            raise OperatorSpecError("max_agents must be at least 6")
        if request.initial_consultants < 0 or request.initial_mentors < 0:
            raise OperatorSpecError("initial role counts must be non-negative")
        roles = 1 + request.initial_consultants + request.initial_mentors
        if roles > request.max_agents:
            raise OperatorSpecError("initial roles exceed max_agents")
        if request.created_at < 0:
            raise OperatorSpecError("created_at must be non-negative")

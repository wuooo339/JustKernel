from __future__ import annotations

from pathlib import Path

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.application.agent_service import AgentService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryClusterRepository,
    InMemoryTaskRepository,
)
from justkernel.application.start_cluster_service import (
    ClusterStartService,
    StartClusterRequest,
)
from justkernel.cluster.operator_spec import (
    AccuracyPolicy,
    CasePackRef,
    EngineeringPolicy,
    OperatorSpec,
    OperatorSpecError,
    OutputTolerance,
    ReferenceSpec,
    TargetSpec,
)
from justkernel.cluster.state import ClusterState, StartMode
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.registry import (
    OperatorActiveError,
    OperatorRegistry,
    apply_registry_schema,
)
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId
from justkernel.shared.paths import ProjectPath
from justkernel.testing.policy import BudgetPolicy, EvaluationPolicy


# ---- fixtures ---------------------------------------------------------------
def _digest(text: str) -> Digest:
    return Digest.from_text(text)


def _skill() -> SkillRef:
    return SkillRef(
        name="tester-cann-simulation",
        version="1",
        source_path="/skills/tester-cann-simulation",
        digest=_digest("skill"),
    )


def _reference() -> ReferenceSpec:
    return ReferenceSpec(
        kind="executable",
        description="reference implementation",
        artifact_digest=_digest("reference"),
    )


def _accuracy() -> AccuracyPolicy:
    return AccuracyPolicy(
        outputs=(OutputTolerance(dtype="float32", atol=1e-5, rtol=1e-5),),
    )


def _case_pack() -> CasePackRef:
    return CasePackRef(digest=_digest("case-pack"), case_count=10, seed=7)


def _spec(
    *,
    performance_target: bool = False,
) -> OperatorSpec:
    reference = _reference()
    accuracy = _accuracy()
    case_pack = _case_pack()
    evaluation = EvaluationPolicy(
        case_pack_digest=case_pack.digest,
        reference_digest=reference.digest(),
        accuracy_policy_digest=accuracy.digest(),
        allowed_backends=("cann-simulation",),
        environment_fingerprint="env-1",
        timing_unit="ms",
        warmup=1,
        repeats=3,
        aggregation="median",
        performance_target_enabled=performance_target,
        profiler_required=performance_target,
    )
    return OperatorSpec(
        operator_id="op-1",
        version="1",
        semantics="operator semantics",
        input_contract="float32 [N,C]",
        reference=reference,
        accuracy_policy=accuracy,
        case_pack=case_pack,
        target=TargetSpec(
            soc="Ascend910B4",
            language="cpp",
            abi="aclnn",
            cann_version="9.0.0",
            build_entry="build.sh",
            run_entry="run.sh",
        ),
        engineering_policy=EngineeringPolicy(
            editable_paths=(ProjectPath("op_kernel/kernel.cpp"),),
            read_only_paths=(ProjectPath("tests/cases.json"),),
            forbidden_actions=("modify oracle",),
        ),
        evaluation_policy=evaluation,
    )


def _request(spec: OperatorSpec, **overrides: object) -> StartClusterRequest:
    values: dict[str, object] = {
        "operator_spec": spec,
        "operator_artifact_ref": "artifact://spec",
        "start_mode": StartMode.GENERATE,
        "baseline_source_ref": None,
        "tester_skill": _skill(),
        "profiler_skill": None,
        "backend": "cann-simulation",
        "devices": ("sim:0",),
        "max_agents": 6,
        "initial_consultants": 1,
        "initial_mentors": 1,
        "model_profile": "model-1",
        "budget": BudgetPolicy(max_duration_s=60),
        "reservation_key": "reservation-1",
        "journal_ref": "journal/cluster-1",
        "created_at": 0,
    }
    values.update(overrides)
    return StartClusterRequest(**values)


def _stack(tmp_path: Path) -> tuple[ClusterStartService, OperatorRegistry]:
    connection = connect(str(tmp_path / "registry.db"))
    apply_registry_schema(connection)
    registry = OperatorRegistry(connection)
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    return ClusterStartService(cluster_service, agent_service, registry), registry


# ---- startup ----------------------------------------------------------------
def test_generate_start_creates_roles_and_runs(tmp_path: Path) -> None:
    service, registry = _stack(tmp_path)
    spec = _spec()
    result = service.start(_request(spec, supervisor_id=AgentId.generate()))

    assert result.cluster.state is ClusterState.RUNNING
    assert result.cluster.phase.value == "BOOTSTRAPPING"
    assert result.supervisor.id == result.cluster.supervisor_id
    assert len(result.consultants) == 1
    assert len(result.mentors) == 1
    assert registry.get_active(spec.operator_id) is not None
    assert result.cluster.operator_id == spec.operator_id


def test_import_requires_baseline_source(tmp_path: Path) -> None:
    service, registry = _stack(tmp_path)
    spec = _spec()

    with pytest.raises(OperatorSpecError):
        service.start(
            _request(
                spec,
                start_mode=StartMode.IMPORT,
                baseline_source_ref=None,
            )
        )
    assert registry.list_active() == ()


def test_performance_target_requires_profiler_skill(tmp_path: Path) -> None:
    service, registry = _stack(tmp_path)
    spec = _spec(performance_target=True)

    with pytest.raises(OperatorSpecError):
        service.start(_request(spec, profiler_skill=None))
    assert registry.list_active() == ()


def test_backend_must_be_allowed(tmp_path: Path) -> None:
    service, registry = _stack(tmp_path)

    with pytest.raises(OperatorSpecError):
        service.start(_request(_spec(), backend="npu"))
    assert registry.list_active() == ()


def test_initial_roles_must_fit_capacity(tmp_path: Path) -> None:
    service, registry = _stack(tmp_path)

    with pytest.raises(OperatorSpecError):
        service.start(_request(_spec(), max_agents=6, initial_mentors=10))
    assert registry.list_active() == ()


def test_duplicate_active_operator_is_a_conflict(tmp_path: Path) -> None:
    service, registry = _stack(tmp_path)
    spec = _spec()
    first = service.start(_request(spec))

    with pytest.raises(OperatorActiveError):
        service.start(
            _request(
                spec,
                reservation_key="reservation-2",
                journal_ref="journal/cluster-2",
            )
        )
    assert registry.get_active(spec.operator_id).cluster_id == first.cluster.id.value


def test_import_with_source_starts(tmp_path: Path) -> None:
    service, _ = _stack(tmp_path)
    spec = _spec()
    result = service.start(
        _request(
            spec,
            start_mode=StartMode.IMPORT,
            baseline_source_ref="artifact://baseline",
        )
    )

    assert result.cluster.state is ClusterState.RUNNING
    assert result.cluster.start_mode is StartMode.IMPORT

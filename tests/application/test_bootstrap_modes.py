from __future__ import annotations

from pathlib import Path

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.application.agent_service import AgentService
from justkernel.application.bootstrap_service import BootstrapService
from justkernel.application.candidate_service import CandidateService
from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeIds,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryDirectionRepository,
    InMemoryTaskRepository,
)
from justkernel.application.start_cluster_service import (
    ClusterStartService,
    StartClusterRequest,
    StartedCluster,
)
from justkernel.cluster.direction import Direction
from justkernel.cluster.errors import DirectionError
from justkernel.cluster.operator_spec import (
    AccuracyPolicy,
    CasePackRef,
    EngineeringPolicy,
    OperatorSpec,
    OutputTolerance,
    ReferenceSpec,
    TargetSpec,
)
from justkernel.cluster.state import ClusterPhase, DirectionState, StartMode
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.registry import OperatorRegistry, apply_registry_schema
from justkernel.shared.digest import Digest
from justkernel.shared.paths import ProjectPath
from justkernel.shared.principal import Principal
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


def _spec() -> OperatorSpec:
    reference = _reference()
    accuracy = _accuracy()
    case_pack = CasePackRef(digest=_digest("case-pack"), case_count=10, seed=7)
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


def _request(spec: OperatorSpec, mode: StartMode, **overrides: object) -> StartClusterRequest:
    values: dict[str, object] = {
        "operator_spec": spec,
        "operator_artifact_ref": "artifact://spec",
        "start_mode": mode,
        "baseline_source_ref": "artifact://baseline" if mode is StartMode.IMPORT else None,
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


def _stack(
    tmp_path: Path,
) -> tuple[
    ClusterStartService,
    BootstrapService,
    InMemoryDirectionRepository,
    InMemoryCandidateRepository,
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = connect(str(tmp_path / "registry.db"))
    apply_registry_schema(connection)
    registry = OperatorRegistry(connection)
    clusters = InMemoryClusterRepository()
    agents = InMemoryAgentRepository()
    tasks = InMemoryTaskRepository()
    candidates = InMemoryCandidateRepository()
    directions = InMemoryDirectionRepository()
    ids = FakeIds()
    cluster_service = ClusterService(clusters, ids)
    agent_service = AgentService(clusters, agents, tasks, ids)
    candidate_service = CandidateService(candidates, tasks, agents, ids)
    start_service = ClusterStartService(cluster_service, agent_service, registry)
    bootstrap = BootstrapService(directions, candidate_service)
    return start_service, bootstrap, directions, candidates


def _started(
    service: ClusterStartService,
    mode: StartMode,
    *,
    initial_mentors: int = 1,
) -> StartedCluster:
    return service.start(
        _request(
            _spec(),
            mode,
            initial_mentors=initial_mentors,
            reservation_key=f"reservation-{mode.value}",
        )
    )


# ---- GENERATE ---------------------------------------------------------------
def test_generate_creates_active_dir_without_candidate(tmp_path: Path) -> None:
    start, bootstrap, directions, candidates = _stack(tmp_path)
    started = _started(start, StartMode.GENERATE)

    direction = bootstrap.generate(
        started=started,
        objective="build the initial implementation",
        constraints=("no reference edits",),
        created_at=10,
    )

    assert isinstance(direction, Direction)
    assert direction.state is DirectionState.ACTIVE
    assert direction.mentor_id == started.mentors[0].id
    assert direction.cluster_id == started.cluster.id
    assert directions.list_by_cluster(started.cluster.id) == (direction,)
    assert candidates.list_by_cluster(started.cluster.id) == ()
    assert started.cluster.phase is ClusterPhase.BOOTSTRAPPING
    assert started.cluster.baseline_candidate_id is None


# ---- IMPORT ----------------------------------------------------------------
def test_import_creates_system_root_candidate(tmp_path: Path) -> None:
    start, bootstrap, directions, candidates = _stack(tmp_path)
    started = _started(start, StartMode.IMPORT)

    imported = bootstrap.import_root(
        started=started,
        source_files={"op_kernel/kernel.cpp": "// imported root"},
        diff_artifact="artifact://diff",
        import_id="import-1",
        objective="validate the imported baseline",
        created_at=10,
    )

    assert imported.candidate.parent_id is None
    assert imported.candidate.task_id is None
    assert imported.candidate.author_agent_id is None
    assert imported.candidate.author_principal == Principal.system()
    assert imported.candidate.import_id == "import-1"
    assert imported.candidate.direction_id == imported.direction.id
    assert imported.direction.state is DirectionState.ACTIVE
    assert candidates.list_by_cluster(started.cluster.id) == (imported.candidate,)
    assert directions.list_by_cluster(started.cluster.id) == (imported.direction,)
    assert started.cluster.baseline_candidate_id is None


# ---- mode/mentor guards -----------------------------------------------------
def test_bootstrap_rejects_wrong_mode(tmp_path: Path) -> None:
    start_generate, bootstrap, directions, candidates = _stack(tmp_path / "generate")
    start_import, _, _, _ = _stack(tmp_path / "import")
    generated = _started(start_generate, StartMode.GENERATE)
    imported = _started(start_import, StartMode.IMPORT)

    with pytest.raises(DirectionError):
        bootstrap.import_root(
            started=generated,
            source_files={"kernel.cpp": "// wrong mode"},
            diff_artifact="artifact://diff",
            import_id="import-1",
            objective="wrong",
            created_at=10,
        )
    with pytest.raises(DirectionError):
        bootstrap.generate(
            started=imported,
            objective="wrong",
            created_at=10,
        )
    assert directions.list_by_cluster(generated.cluster.id) == ()
    assert candidates.list_by_cluster(generated.cluster.id) == ()


def test_bootstrap_requires_mentor(tmp_path: Path) -> None:
    start, bootstrap, directions, candidates = _stack(tmp_path)
    started = _started(start, StartMode.GENERATE, initial_mentors=0)

    with pytest.raises(DirectionError):
        bootstrap.generate(started=started, objective="no mentor", created_at=10)
    assert directions.list_by_cluster(started.cluster.id) == ()
    assert candidates.list_by_cluster(started.cluster.id) == ()

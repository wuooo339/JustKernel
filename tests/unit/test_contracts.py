from __future__ import annotations

from dataclasses import replace

import pytest

from justkernel.agent.model_routing import ModelRouting
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
from justkernel.comm.wake import WakePolicy
from justkernel.shared.digest import Digest
from justkernel.shared.ids import TaskId
from justkernel.shared.paths import ProjectPath
from justkernel.task.context import (
    ArtifactGrant,
    EmptyReason,
    TaskBudget,
    TaskContext,
    TaskContextError,
)
from justkernel.testing.policy import BudgetPolicy, EvaluationPolicy, PolicyError


# ---- helpers ----------------------------------------------------------------
def _digest(text: str) -> Digest:
    return Digest.from_text(text)


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
    return CasePackRef(
        digest=_digest("case-pack"),
        case_count=10,
        seed=7,
        coverage_tags=("full",),
    )


def _evaluation(
    reference: ReferenceSpec,
    accuracy: AccuracyPolicy,
    case_pack: CasePackRef,
    *,
    performance_target_enabled: bool = False,
    profiler_required: bool = False,
) -> EvaluationPolicy:
    return EvaluationPolicy(
        case_pack_digest=case_pack.digest,
        reference_digest=reference.digest(),
        accuracy_policy_digest=accuracy.digest(),
        allowed_backends=("cann-simulation",),
        environment_fingerprint="env-1",
        timing_unit="ms",
        warmup=1,
        repeats=3,
        aggregation="median",
        performance_target_enabled=performance_target_enabled,
        profiler_required=profiler_required,
    )


def _spec_kwargs() -> dict[str, object]:
    reference = _reference()
    accuracy = _accuracy()
    case_pack = _case_pack()
    return {
        "operator_id": "ConfusionMulGrad",
        "version": "1",
        "semantics": "confusion matrix gradient",
        "input_contract": "float32 [N, C]",
        "reference": reference,
        "accuracy_policy": accuracy,
        "case_pack": case_pack,
        "target": TargetSpec(
            soc="Ascend910B4",
            language="cpp",
            abi="aclnn",
            cann_version="9.0.0",
            build_entry="build.sh",
            run_entry="run.sh",
        ),
        "engineering_policy": EngineeringPolicy(
            editable_paths=(ProjectPath("op_kernel/kernel.cpp"),),
            read_only_paths=(ProjectPath("tests/cases.json"),),
            forbidden_actions=("modify oracle",),
        ),
        "evaluation_policy": _evaluation(reference, accuracy, case_pack),
    }


def _spec() -> OperatorSpec:
    return OperatorSpec(**_spec_kwargs())


# ---- OperatorSpec -----------------------------------------------------------
def test_operator_spec_digest_and_ref() -> None:
    spec = _spec()
    ref = spec.to_ref("artifact://spec")

    assert spec.digest() == _spec().digest()
    assert ref.digest == spec.digest()
    assert ref.operator_id == spec.operator_id
    assert ref.version == spec.version
    assert ref.artifact_ref == "artifact://spec"


def test_operator_spec_requires_all_fields() -> None:
    fields = _spec_kwargs()
    fields.pop("semantics")

    with pytest.raises(TypeError):
        OperatorSpec(**fields)


def test_operator_spec_rejects_inconsistent_evaluation_digest() -> None:
    fields = _spec_kwargs()
    evaluation = fields["evaluation_policy"]
    assert isinstance(evaluation, EvaluationPolicy)
    fields["evaluation_policy"] = replace(evaluation, case_pack_digest=_digest("other"))

    with pytest.raises(OperatorSpecError):
        OperatorSpec(**fields)


def test_executable_reference_requires_digest() -> None:
    with pytest.raises(OperatorSpecError):
        ReferenceSpec(kind="executable", description="reference")


def test_case_pack_subset_requires_selection_rule() -> None:
    with pytest.raises(OperatorSpecError):
        CasePackRef(
            digest=_digest("subset"),
            case_count=2,
            seed=1,
            subset_of=_digest("full"),
        )


# ---- policies ---------------------------------------------------------------
def test_budget_requires_global_hard_cap_and_reserves_final_validation() -> None:
    with pytest.raises(PolicyError):
        BudgetPolicy()

    with pytest.raises(PolicyError):
        BudgetPolicy(max_bootstrap_attempts=5, plateau_rounds=5)

    policy = BudgetPolicy(max_duration_s=60, final_validation_reserve=10)
    assert policy.max_duration_s == 60
    assert policy.final_validation_reserve == 10


def test_performance_target_requires_profiler() -> None:
    reference = _reference()
    accuracy = _accuracy()
    case_pack = _case_pack()

    with pytest.raises(PolicyError):
        _evaluation(
            reference,
            accuracy,
            case_pack,
            performance_target_enabled=True,
            profiler_required=False,
        )

    policy = _evaluation(
        reference,
        accuracy,
        case_pack,
        performance_target_enabled=True,
        profiler_required=True,
    )
    assert policy.profiler_required is True


def test_wake_policy_defaults_and_validation() -> None:
    policy = WakePolicy()

    assert policy.wake_debounce_ms == 500
    assert policy.summary_interval_s == 30
    assert policy.wait_deadline_s == 300
    assert policy.stalled_timeout_s == 60
    assert policy.max_stalled_wakes == 1

    with pytest.raises(PolicyError):
        WakePolicy(wake_debounce_ms=-1)
    with pytest.raises(PolicyError):
        WakePolicy(max_stalled_wakes=0)


def test_model_routing_priority_and_fallback() -> None:
    routing = ModelRouting(
        system_default="system",
        role_defaults=(("MENTOR", "mentor"),),
        direction_defaults=(("direction-1", "direction"),),
        allowed_fallbacks=("fallback",),
    )

    assert routing.resolve("MENTOR") == "mentor"
    assert routing.resolve("MENTOR", direction_id="direction-1") == "direction"
    assert routing.resolve("MENTOR", direction_id="direction-1", task_profile="task") == "task"
    assert (
        routing.resolve(
            "MENTOR",
            direction_id="direction-1",
            task_profile="task",
            instance_profile="instance",
        )
        == "instance"
    )
    assert routing.resolve("TESTER") == "system"
    assert routing.fallback_allowed("fallback")
    assert not routing.fallback_allowed("other")


# ---- TaskContext ------------------------------------------------------------
def _budget() -> TaskBudget:
    return TaskBudget(max_duration_s=100, remaining_duration_s=50)


def _context_kwargs() -> dict[str, object]:
    spec = _spec()
    task_id = TaskId.generate()
    return {
        "task_id": task_id,
        "operator_spec_ref": spec.to_ref("artifact://spec"),
        "base_candidate_ref": None,
        "objective": "fix compile failure",
        "acceptance": ("compile and pass full tests",),
        "feedback": (),
        "history": (),
        "shared_evidence": (),
        "resource_grants": (),
        "budget": _budget(),
        "empty_reasons": (
            EmptyReason("feedback", "no prior evidence"),
            EmptyReason("history", "first attempt"),
            EmptyReason("shared_evidence", "no shared evidence"),
            EmptyReason("resource_grants", "no artifacts granted"),
        ),
    }


def test_task_context_digest_and_ref() -> None:
    fields = _context_kwargs()
    context = TaskContext(**fields)
    ref = context.to_ref("artifact://context")

    assert context.digest() == TaskContext(**fields).digest()
    assert ref.digest == context.digest()
    assert ref.artifact_ref == "artifact://context"


def test_task_context_requires_empty_reasons() -> None:
    fields = _context_kwargs()
    fields["empty_reasons"] = ()

    with pytest.raises(TaskContextError):
        TaskContext(**fields)


def test_task_context_grant_must_match_task() -> None:
    fields = _context_kwargs()
    grant = ArtifactGrant(
        grant_id="grant-1",
        task_id=TaskId.generate(),
        artifact_digest=_digest("log"),
        readonly_scope=(ProjectPath("logs/run.log"),),
        expires_at_ms=1000,
    )
    fields["resource_grants"] = (grant,)
    fields["empty_reasons"] = (
        EmptyReason("feedback", "no prior evidence"),
        EmptyReason("history", "first attempt"),
        EmptyReason("shared_evidence", "no shared evidence"),
    )

    with pytest.raises(TaskContextError):
        TaskContext(**fields)


def test_task_budget_remaining_cannot_exceed_limit() -> None:
    with pytest.raises(TaskContextError):
        TaskBudget(max_duration_s=10, remaining_duration_s=11)

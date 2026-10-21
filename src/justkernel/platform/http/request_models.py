"""HTTP request models and domain request mapping."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from justkernel.agent.skills import SkillRef
from justkernel.application.start_cluster_service import StartClusterRequest
from justkernel.cluster.operator_spec import (
    AccuracyPolicy,
    CasePackRef,
    EngineeringPolicy,
    OperatorSpec,
    OperatorSpecError,
    OutputTolerance,
    ReferenceSpec,
    TargetSpec,
    TemplateRef,
)
from justkernel.cluster.state import StartMode
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId
from justkernel.shared.paths import ProjectPath
from justkernel.testing.policy import BudgetPolicy, EvaluationPolicy


class SkillPayload(BaseModel):
    name: str
    version: str
    source_path: str
    digest: str


class ClusterCreateBody(BaseModel):
    operator_spec: dict[str, Any]
    operator_artifact_ref: str
    start_mode: Literal["GENERATE", "IMPORT"]
    baseline_source_ref: str | None = None
    tester_skill: SkillPayload
    profiler_skill: SkillPayload | None = None
    backend: str
    devices: list[str] = Field(default_factory=list)
    max_agents: int = 100
    initial_consultants: int = 2
    initial_mentors: int = 4
    model_profile: str
    budget: dict[str, Any]
    reservation_key: str
    journal_ref: str
    created_at: int = 0
    supervisor_id: str | None = None

    def to_start_request(self) -> StartClusterRequest:
        return StartClusterRequest(
            operator_spec=_operator_spec(self.operator_spec),
            operator_artifact_ref=self.operator_artifact_ref,
            start_mode=StartMode(self.start_mode),
            baseline_source_ref=self.baseline_source_ref,
            tester_skill=_skill(self.tester_skill),
            profiler_skill=_skill(self.profiler_skill) if self.profiler_skill else None,
            backend=self.backend,
            devices=tuple(self.devices),
            max_agents=self.max_agents,
            initial_consultants=self.initial_consultants,
            initial_mentors=self.initial_mentors,
            model_profile=self.model_profile,
            budget=_budget(self.budget),
            reservation_key=self.reservation_key,
            journal_ref=self.journal_ref,
            created_at=self.created_at,
            supervisor_id=AgentId(self.supervisor_id) if self.supervisor_id else None,
        )


def _skill(payload: SkillPayload) -> SkillRef:
    return SkillRef(
        name=payload.name,
        version=payload.version,
        source_path=payload.source_path,
        digest=Digest(payload.digest),
    )


def _budget(payload: dict[str, Any]) -> BudgetPolicy:
    return BudgetPolicy(**payload)


def _operator_spec(payload: dict[str, Any]) -> OperatorSpec:
    try:
        return OperatorSpec(
            operator_id=payload["operator_id"],
            version=payload["version"],
            semantics=payload["semantics"],
            input_contract=payload["input_contract"],
            reference=_reference(payload["reference"]),
            accuracy_policy=_accuracy(payload["accuracy_policy"]),
            case_pack=_case_pack(payload["case_pack"]),
            target=_target(payload["target"]),
            engineering_policy=_engineering(payload["engineering_policy"]),
            evaluation_policy=_evaluation(payload["evaluation_policy"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise OperatorSpecError(f"invalid operator spec: {error}") from error


def _reference(payload: dict[str, Any]) -> ReferenceSpec:
    return ReferenceSpec(
        kind=payload["kind"],
        description=payload["description"],
        artifact_digest=(
            Digest(payload["artifact_digest"]) if payload.get("artifact_digest") else None
        ),
        oracle=payload.get("oracle"),
    )


def _accuracy(payload: dict[str, Any]) -> AccuracyPolicy:
    return AccuracyPolicy(
        outputs=tuple(
            OutputTolerance(dtype=item["dtype"], atol=item["atol"], rtol=item["rtol"])
            for item in payload["outputs"]
        ),
        nan_policy=payload.get("nan_policy", "reject"),
        comparison=payload.get("comparison", "elementwise"),
    )


def _case_pack(payload: dict[str, Any]) -> CasePackRef:
    return CasePackRef(
        digest=Digest(payload["digest"]),
        case_count=payload["case_count"],
        seed=payload["seed"],
        coverage_tags=tuple(payload.get("coverage_tags", ())),
        subset_of=Digest(payload["subset_of"]) if payload.get("subset_of") else None,
        selection_rule=payload.get("selection_rule"),
    )


def _target(payload: dict[str, Any]) -> TargetSpec:
    return TargetSpec(
        soc=payload["soc"],
        language=payload["language"],
        abi=payload["abi"],
        cann_version=payload["cann_version"],
        build_entry=payload["build_entry"],
        run_entry=payload["run_entry"],
        memory_limit_bytes=payload.get("memory_limit_bytes"),
    )


def _engineering(payload: dict[str, Any]) -> EngineeringPolicy:
    return EngineeringPolicy(
        editable_paths=tuple(ProjectPath(path) for path in payload["editable_paths"]),
        read_only_paths=tuple(ProjectPath(path) for path in payload["read_only_paths"]),
        forbidden_actions=tuple(payload["forbidden_actions"]),
        templates=tuple(
            TemplateRef(name=item["name"], digest=Digest(item["digest"]))
            for item in payload.get("templates", ())
        ),
    )


def _evaluation(payload: dict[str, Any]) -> EvaluationPolicy:
    return EvaluationPolicy(
        case_pack_digest=Digest(payload["case_pack_digest"]),
        reference_digest=Digest(payload["reference_digest"]),
        accuracy_policy_digest=Digest(payload["accuracy_policy_digest"]),
        allowed_backends=tuple(payload["allowed_backends"]),
        environment_fingerprint=payload["environment_fingerprint"],
        timing_unit=payload["timing_unit"],
        warmup=payload["warmup"],
        repeats=payload["repeats"],
        aggregation=payload["aggregation"],
        aggregation_params=tuple(
            (name, value) for name, value in payload.get("aggregation_params", ())
        ),
        per_case_regression_limit=payload.get("per_case_regression_limit"),
        min_improvement=payload.get("min_improvement", 0.0),
        performance_target_enabled=payload.get("performance_target_enabled", False),
        profiler_required=payload.get("profiler_required", False),
    )

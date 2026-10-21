"""Immutable operator specification and its reference."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal

from justkernel.shared.digest import Digest
from justkernel.shared.errors import JustKernelError
from justkernel.shared.json import digest_json
from justkernel.shared.paths import ProjectPath
from justkernel.testing.policy import EvaluationPolicy


# ---- OperatorSpecError ------------------------------------------------------
class OperatorSpecError(JustKernelError):
    code = "operator_spec.incomplete"


# ---- ReferenceSpec ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReferenceSpec:
    kind: Literal["executable", "oracle"]
    description: str
    artifact_digest: Digest | None = None
    oracle: str | None = None

    def __post_init__(self) -> None:
        if not self.description:
            raise OperatorSpecError("reference description must be non-empty")
        if self.kind == "executable":
            if self.artifact_digest is None or self.oracle is not None:
                raise OperatorSpecError("executable reference requires artifact_digest only")
        elif self.kind == "oracle":
            if not self.oracle or self.artifact_digest is not None:
                raise OperatorSpecError("oracle reference requires oracle text only")
        else:
            raise OperatorSpecError(f"unknown reference kind {self.kind!r}")

    def digest(self) -> Digest:
        return digest_json(asdict(self))


# ---- AccuracyPolicy ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OutputTolerance:
    dtype: str
    atol: float
    rtol: float

    def __post_init__(self) -> None:
        if not self.dtype:
            raise OperatorSpecError("accuracy dtype must be non-empty")
        for name, value in (("atol", self.atol), ("rtol", self.rtol)):
            if not math.isfinite(value) or value < 0:
                raise OperatorSpecError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class AccuracyPolicy:
    outputs: tuple[OutputTolerance, ...]
    nan_policy: Literal["reject", "equal", "ignore"] = "reject"
    comparison: str = "elementwise"

    def __post_init__(self) -> None:
        if not self.outputs:
            raise OperatorSpecError("accuracy policy requires at least one output")
        dtypes = [output.dtype for output in self.outputs]
        if len(set(dtypes)) != len(dtypes):
            raise OperatorSpecError("accuracy output dtypes must be unique")
        if self.nan_policy not in ("reject", "equal", "ignore"):
            raise OperatorSpecError(f"unknown nan_policy {self.nan_policy!r}")
        if not self.comparison:
            raise OperatorSpecError("comparison must be non-empty")

    def digest(self) -> Digest:
        return digest_json(asdict(self))


# ---- CasePackRef ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CasePackRef:
    digest: Digest
    case_count: int
    seed: int
    coverage_tags: tuple[str, ...] = ()
    subset_of: Digest | None = None
    selection_rule: str | None = None

    def __post_init__(self) -> None:
        if self.case_count < 1:
            raise OperatorSpecError("case_count must be positive")
        if self.seed < 0:
            raise OperatorSpecError("seed must be non-negative")
        if any(not tag for tag in self.coverage_tags):
            raise OperatorSpecError("coverage tags must be non-empty")
        if (self.subset_of is None) != (self.selection_rule is None):
            raise OperatorSpecError("subset_of and selection_rule must be provided together")


# ---- TargetSpec -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TargetSpec:
    soc: str
    language: str
    abi: str
    cann_version: str
    build_entry: str
    run_entry: str
    memory_limit_bytes: int | None = None

    def __post_init__(self) -> None:
        for name in ("soc", "language", "abi", "cann_version", "build_entry", "run_entry"):
            if not getattr(self, name):
                raise OperatorSpecError(f"{name} must be non-empty")
        if self.memory_limit_bytes is not None and self.memory_limit_bytes <= 0:
            raise OperatorSpecError("memory_limit_bytes must be positive")


# ---- EngineeringPolicy ------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TemplateRef:
    name: str
    digest: Digest

    def __post_init__(self) -> None:
        if not self.name:
            raise OperatorSpecError("template name must be non-empty")


@dataclass(frozen=True, slots=True)
class EngineeringPolicy:
    editable_paths: tuple[ProjectPath, ...]
    read_only_paths: tuple[ProjectPath, ...]
    forbidden_actions: tuple[str, ...]
    templates: tuple[TemplateRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.editable_paths or not self.read_only_paths:
            raise OperatorSpecError("editable and read-only paths must be non-empty")
        if not self.forbidden_actions or any(not action for action in self.forbidden_actions):
            raise OperatorSpecError("forbidden_actions must be non-empty")
        editable = set(self.editable_paths)
        read_only = set(self.read_only_paths)
        if editable & read_only:
            raise OperatorSpecError("editable and read-only paths must not overlap")
        names = [template.name for template in self.templates]
        if len(set(names)) != len(names):
            raise OperatorSpecError("template names must be unique")


# ---- OperatorSpec -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OperatorSpec:
    operator_id: str
    version: str
    semantics: str
    input_contract: str
    reference: ReferenceSpec
    accuracy_policy: AccuracyPolicy
    case_pack: CasePackRef
    target: TargetSpec
    engineering_policy: EngineeringPolicy
    evaluation_policy: EvaluationPolicy

    def __post_init__(self) -> None:
        for name in ("operator_id", "version", "semantics", "input_contract"):
            if not getattr(self, name):
                raise OperatorSpecError(f"{name} must be non-empty")
        if self.evaluation_policy.case_pack_digest != self.case_pack.digest:
            raise OperatorSpecError("evaluation policy case pack digest does not match")
        if self.evaluation_policy.reference_digest != self.reference.digest():
            raise OperatorSpecError("evaluation policy reference digest does not match")
        if self.evaluation_policy.accuracy_policy_digest != self.accuracy_policy.digest():
            raise OperatorSpecError("evaluation policy accuracy digest does not match")

    def digest(self) -> Digest:
        return digest_json(asdict(self))

    def to_ref(self, artifact_ref: str) -> OperatorRef:
        return OperatorRef(
            operator_id=self.operator_id,
            version=self.version,
            digest=self.digest(),
            artifact_ref=artifact_ref,
        )


# ---- OperatorRef ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OperatorRef:
    operator_id: str
    version: str
    digest: Digest
    artifact_ref: str

    def __post_init__(self) -> None:
        for name in ("operator_id", "version", "artifact_ref"):
            if not getattr(self, name):
                raise OperatorSpecError(f"{name} must be non-empty")

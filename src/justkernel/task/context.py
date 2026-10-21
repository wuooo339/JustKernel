"""Immutable task context and feedback snapshot."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from justkernel.cluster.operator_spec import OperatorRef
from justkernel.shared.digest import Digest
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.ids import CandidateId, TaskId, TestRecordId
from justkernel.shared.json import digest_json
from justkernel.shared.paths import ProjectPath

CONTEXT_LIST_FIELDS = ("feedback", "history", "shared_evidence", "resource_grants")


# ---- TaskContextError -------------------------------------------------------
class TaskContextError(JustKernelError):
    code = ErrorCode.INVALID_TASK_CONTEXT


# ---- _require_text ----------------------------------------------------------
def _require_text(name: str, value: str) -> None:
    if not value:
        raise TaskContextError(f"{name} must be non-empty")


# ---- _require_unique_text ---------------------------------------------------
def _require_unique_text(name: str, values: tuple[str, ...]) -> None:
    if not values or any(not value for value in values):
        raise TaskContextError(f"{name} must be non-empty")
    if len(set(values)) != len(values):
        raise TaskContextError(f"{name} must be unique")


# ---- CandidateRef -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CandidateRef:
    candidate_id: CandidateId
    source_digest: Digest


# ---- FeedbackRef ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FeedbackRef:
    summary: str
    record_id: TestRecordId | None = None
    task_id: TaskId | None = None
    artifact_ref: str | None = None
    failure_stage: str | None = None
    failed_cases: tuple[str, ...] = ()
    environment_digest: Digest | None = None

    def __post_init__(self) -> None:
        _require_text("summary", self.summary)
        if self.record_id is None and self.task_id is None and not self.artifact_ref:
            raise TaskContextError("feedback requires a record, task, or artifact reference")
        if self.failure_stage is not None:
            _require_text("failure_stage", self.failure_stage)
        if any(not case for case in self.failed_cases):
            raise TaskContextError("failed_cases must not contain empty values")


# ---- HistoryEntry -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class HistoryEntry:
    candidate_id: CandidateId
    source_digest: Digest
    hypothesis: str
    result: str
    rejected_reason: str | None = None
    known_limits: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("hypothesis", self.hypothesis)
        _require_text("result", self.result)
        if self.rejected_reason is not None:
            _require_text("rejected_reason", self.rejected_reason)
        if any(not limit for limit in self.known_limits):
            raise TaskContextError("known_limits must not contain empty values")


# ---- SharedEvidence ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SharedEvidence:
    summary: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text("summary", self.summary)
        _require_unique_text("evidence_refs", self.evidence_refs)


# ---- ArtifactGrant ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtifactGrant:
    grant_id: str
    task_id: TaskId
    artifact_digest: Digest
    readonly_scope: tuple[ProjectPath, ...]
    expires_at_ms: int

    def __post_init__(self) -> None:
        _require_text("grant_id", self.grant_id)
        if not self.readonly_scope:
            raise TaskContextError("readonly_scope must be non-empty")
        if self.expires_at_ms <= 0:
            raise TaskContextError("expires_at_ms must be positive")


# ---- EmptyReason ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EmptyReason:
    field: str
    reason: str

    def __post_init__(self) -> None:
        if self.field not in CONTEXT_LIST_FIELDS:
            raise TaskContextError(f"unknown context list field {self.field!r}")
        _require_text("reason", self.reason)


# ---- TaskBudget -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TaskBudget:
    max_duration_s: int | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    max_generation_attempts: int | None = None
    max_tool_seconds: int | None = None
    max_device_seconds: int | None = None
    remaining_duration_s: int | None = None
    remaining_tokens: int | None = None
    remaining_cost_usd: float | None = None
    remaining_generation_attempts: int | None = None
    remaining_tool_seconds: int | None = None
    remaining_device_seconds: int | None = None

    def __post_init__(self) -> None:
        self._require_limit()
        self._check_non_negative()
        self._check_remaining()

    def _require_limit(self) -> None:
        limits = (
            self.max_duration_s,
            self.max_tokens,
            self.max_cost_usd,
            self.max_generation_attempts,
            self.max_tool_seconds,
            self.max_device_seconds,
        )
        if all(limit is None for limit in limits):
            raise TaskContextError("task budget requires at least one limit")

    def _check_non_negative(self) -> None:
        for name in (
            "max_duration_s",
            "max_tokens",
            "max_generation_attempts",
            "max_tool_seconds",
            "max_device_seconds",
            "remaining_duration_s",
            "remaining_tokens",
            "remaining_generation_attempts",
            "remaining_tool_seconds",
            "remaining_device_seconds",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise TaskContextError(f"{name} must be non-negative")
        for name in ("max_cost_usd", "remaining_cost_usd"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise TaskContextError(f"{name} must be finite and non-negative")

    def _check_remaining(self) -> None:
        pairs = (
            ("max_duration_s", "remaining_duration_s"),
            ("max_tokens", "remaining_tokens"),
            ("max_cost_usd", "remaining_cost_usd"),
            ("max_generation_attempts", "remaining_generation_attempts"),
            ("max_tool_seconds", "remaining_tool_seconds"),
            ("max_device_seconds", "remaining_device_seconds"),
        )
        for limit_name, remaining_name in pairs:
            limit = getattr(self, limit_name)
            remaining = getattr(self, remaining_name)
            if limit is not None and remaining is not None and remaining > limit:
                raise TaskContextError(f"{remaining_name} must not exceed {limit_name}")

    def digest(self) -> Digest:
        return digest_json(asdict(self))


# ---- TaskContext ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TaskContext:
    task_id: TaskId
    operator_spec_ref: OperatorRef
    base_candidate_ref: CandidateRef | None
    objective: str
    acceptance: tuple[str, ...]
    feedback: tuple[FeedbackRef, ...]
    history: tuple[HistoryEntry, ...]
    shared_evidence: tuple[SharedEvidence, ...]
    resource_grants: tuple[ArtifactGrant, ...]
    budget: TaskBudget
    empty_reasons: tuple[EmptyReason, ...] = ()

    def __post_init__(self) -> None:
        _require_text("objective", self.objective)
        _require_unique_text("acceptance", self.acceptance)
        for grant in self.resource_grants:
            if grant.task_id != self.task_id:
                raise TaskContextError("artifact grant task_id must match context task_id")
        empty_fields = {name for name in CONTEXT_LIST_FIELDS if not getattr(self, name)}
        reason_fields = {reason.field for reason in self.empty_reasons}
        if empty_fields != reason_fields:
            raise TaskContextError("each empty context list needs exactly one reason")

    def digest(self) -> Digest:
        return digest_json(asdict(self))

    def to_ref(self, artifact_ref: str) -> TaskContextRef:
        _require_text("artifact_ref", artifact_ref)
        return TaskContextRef(artifact_ref=artifact_ref, digest=self.digest())


# ---- TaskContextRef ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TaskContextRef:
    artifact_ref: str
    digest: Digest

    def __post_init__(self) -> None:
        _require_text("artifact_ref", self.artifact_ref)

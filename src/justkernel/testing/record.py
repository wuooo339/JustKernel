"""Immutable TestRecord."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.skills import SkillRef
from justkernel.shared.digest import Digest
from justkernel.shared.ids import CandidateId, TaskId, TestRecordId
from justkernel.shared.json import digest_json
from justkernel.testing.errors import TestRecordError
from justkernel.testing.state import TestCoverage, TestOutcome, TestRecordKind


# ---- ArtifactRef ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ArtifactRef:
    ref: str
    digest: Digest

    def __post_init__(self) -> None:
        if not self.ref:
            raise TestRecordError("artifact ref must be non-empty")


# ---- Environment ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Environment:
    values: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise TestRecordError("environment must not be empty")
        keys = [key for key, _ in self.values]
        if any(not key or not value for key, value in self.values):
            raise TestRecordError("environment keys and values must be non-empty")
        if len(set(keys)) != len(keys):
            raise TestRecordError("environment keys must be unique")

    def digest(self) -> Digest:
        return digest_json(tuple(sorted(self.values)))


# ---- TestRecord -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TestRecord:
    id: TestRecordId
    candidate_id: CandidateId
    kind: TestRecordKind
    skill_ref: SkillRef
    backend: str
    outcome: TestOutcome
    coverage: TestCoverage
    executed: bool
    artifact: ArtifactRef
    environment: Environment
    created_at: int
    task_id: TaskId | None = None
    job_id: str | None = None
    audit_id: str | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.backend:
            raise TestRecordError("backend must be non-empty")
        if self.created_at < 0:
            raise TestRecordError("created_at must be non-negative")
        self._check_execution()
        if self.outcome is TestOutcome.PASS and not self.executed:
            raise TestRecordError("PASS requires an executed record")

    def _check_execution(self) -> None:
        if self.executed:
            if self.task_id is None or not self.job_id:
                raise TestRecordError("executed record requires task_id and job_id")
            if self.audit_id is not None:
                raise TestRecordError("executed record must not have audit_id")
            if self.coverage is TestCoverage.NONE:
                raise TestRecordError("executed record requires FULL or SUBSET coverage")
        else:
            if self.task_id is not None or self.job_id is not None:
                raise TestRecordError("audit record must not have task_id or job_id")
            if not self.audit_id:
                raise TestRecordError("audit record requires audit_id")
            if self.coverage is not TestCoverage.NONE:
                raise TestRecordError("audit record requires NONE coverage")
            if self.outcome not in (TestOutcome.CANCELLED, TestOutcome.UNKNOWN):
                raise TestRecordError("audit outcome must be CANCELLED or UNKNOWN")

    @property
    def is_full_pass(self) -> bool:
        return (
            self.executed
            and self.outcome is TestOutcome.PASS
            and self.coverage is TestCoverage.FULL
        )

    @property
    def is_audit(self) -> bool:
        return not self.executed

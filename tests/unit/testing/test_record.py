from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.shared.digest import Digest
from justkernel.shared.ids import CandidateId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.testing.errors import TestRecordError as RecordError
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- helpers ----------------------------------------------------------------
def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation",
        version="1",
        source_path="/skills/builtin/tester-cann-simulation",
        digest=Digest.from_text("skill"),
    )


def _artifact() -> ArtifactRef:
    return ArtifactRef(ref="artifact://record.zip", digest=Digest.from_text("zip"))


def _environment() -> Environment:
    return Environment(
        values=(
            ("cann", "9.0.0"),
            ("soc", "Ascend910B4"),
        )
    )


def _record(**overrides: object) -> Record:
    values: dict[str, object] = {
        "id": RecordId.generate(),
        "candidate_id": CandidateId.generate(),
        "kind": RecordKind.TEST,
        "skill_ref": _skill(),
        "backend": "cann-simulation",
        "outcome": Outcome.PASS,
        "coverage": Coverage.FULL,
        "executed": True,
        "artifact": _artifact(),
        "environment": _environment(),
        "created_at": 0,
        "task_id": TaskId.generate(),
        "job_id": "job-1",
    }
    values.update(overrides)
    return Record(**values)


# ---- executed records -------------------------------------------------------
def test_executed_full_pass() -> None:
    record = _record()

    assert record.is_full_pass is True
    assert record.is_audit is False
    assert record.environment.digest() == _environment().digest()


def test_executed_record_requires_task_and_job() -> None:
    with pytest.raises(RecordError):
        _record(task_id=None)
    with pytest.raises(RecordError):
        _record(job_id=None)
    with pytest.raises(RecordError):
        _record(audit_id="audit-1")


def test_pass_requires_execution_and_coverage() -> None:
    with pytest.raises(RecordError):
        _record(coverage=Coverage.NONE)
    with pytest.raises(RecordError):
        _record(
            executed=False,
            task_id=None,
            job_id=None,
            audit_id="audit-1",
            coverage=Coverage.NONE,
            outcome=Outcome.PASS,
        )


# ---- audit records ----------------------------------------------------------
def test_audit_record() -> None:
    record = _record(
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )

    assert record.is_audit is True
    assert record.is_full_pass is False


def test_audit_record_requires_no_task_or_job_and_audit_outcome() -> None:
    with pytest.raises(RecordError):
        _record(
            executed=False,
            task_id=TaskId.generate(),
            job_id=None,
            audit_id="audit-1",
            coverage=Coverage.NONE,
            outcome=Outcome.CANCELLED,
        )
    with pytest.raises(RecordError):
        _record(
            executed=False,
            task_id=None,
            job_id=None,
            audit_id=None,
            coverage=Coverage.NONE,
            outcome=Outcome.CANCELLED,
        )
    with pytest.raises(RecordError):
        _record(
            executed=False,
            task_id=None,
            job_id=None,
            audit_id="audit-1",
            coverage=Coverage.FULL,
            outcome=Outcome.UNKNOWN,
        )


# ---- immutability and helpers ----------------------------------------------
def test_record_is_frozen() -> None:
    record = _record()

    with pytest.raises(FrozenInstanceError):
        record.backend = "other"


def test_artifact_and_environment_validation() -> None:
    with pytest.raises(RecordError):
        ArtifactRef(ref="", digest=Digest.from_text("zip"))
    with pytest.raises(RecordError):
        Environment(values=(("soc", "A"), ("soc", "B")))
    with pytest.raises(RecordError):
        Environment(values=())

from __future__ import annotations

import io
import json
import zipfile

import pytest

from justkernel.agent.skills import SkillRef
from justkernel.shared.digest import Digest
from justkernel.shared.ids import CandidateId, TaskId
from justkernel.shared.ids import TestRecordId as RecordId
from justkernel.testing.errors import TestRecordError as RecordError
from justkernel.testing.record import ArtifactRef, Environment
from justkernel.testing.record import TestRecord as Record
from justkernel.testing.record_zip import (
    RecordZipError,
    build_audit_record_zip,
    build_record_zip,
    validate_record_zip,
)
from justkernel.testing.state import TestCoverage as Coverage
from justkernel.testing.state import TestOutcome as Outcome
from justkernel.testing.state import TestRecordKind as RecordKind


# ---- helpers ----------------------------------------------------------------
def _skill() -> SkillRef:
    return SkillRef(
        name="cann-simulation",
        version="1",
        source_path="/skills/tester",
        digest=Digest.from_text("skill"),
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
        "artifact": ArtifactRef(ref="artifact://record.zip", digest=Digest.from_text("zip")),
        "environment": Environment(values=(("soc", "Ascend910B4"),)),
        "created_at": 0,
        "task_id": TaskId.generate(),
        "job_id": "job-1",
    }
    values.update(overrides)
    return Record(**values)


def _payloads() -> dict[str, str | bytes]:
    return {
        "task.json": '{"task_id":"task-1"}',
        "context.json": "{}",
        "operator-spec.json": "{}",
        "candidate/diff.patch": "diff --git a/kernel.cpp b/kernel.cpp",
        "candidate/source.sha256": "source-digest  kernel.cpp\n",
        "candidate/source/kernel.cpp": "// kernel source\n",
        "skill/SKILL.md": "# tester\n",
        "skill/metadata.json": '{"name":"cann-simulation"}',
        "cases.json": "[]",
        "config.json": "{}",
        "environment.json": '{"soc":"Ascend910B4"}',
        "commands.log": "compile\nrun\n",
        "stdout.log": "ok\n",
        "stderr.log": "",
        "results.json": '{"outcome":"PASS","executed":true}',
        "metrics.json": "{}",
        "provenance.json": "{}",
    }


def _audit_payloads() -> dict[str, str | bytes]:
    payloads = _payloads()
    payloads["commands.log"] = "NOT EXECUTED\n"
    payloads["results.json"] = '{"outcome":"CANCELLED","executed":false}'
    payloads["metrics.json"] = "{}"
    return payloads


def _rewrite(
    data: bytes, *, remove: str | None = None, replace: dict[str, bytes] | None = None
) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename == remove:
                continue
            content = (replace or {}).get(info.filename, source.read(info.filename))
            target.writestr(info.filename, content)
    return output.getvalue()


# ---- builder/validator ------------------------------------------------------
def test_build_and_validate_executed_record() -> None:
    record = _record()
    data = build_record_zip(record, cluster_id="cluster-1", payloads=_payloads())

    validation = validate_record_zip(data, expected_record_id=record.id.value)
    assert validation.record_id == record.id.value
    assert validation.manifest["schema"] == "justkernel.test_record.v1"
    assert validation.manifest["executed"] is True
    assert validation.manifest["outcome"] == "PASS"
    assert "manifest.json" in validation.files
    assert "checksums.sha256" in validation.files

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.read("candidate/source/kernel.cpp") == b"// kernel source\n"


def test_missing_required_payload_is_rejected() -> None:
    payloads = _payloads()
    del payloads["results.json"]

    with pytest.raises(RecordZipError):
        build_record_zip(_record(), cluster_id="cluster-1", payloads=payloads)


def test_missing_file_in_existing_zip_is_rejected() -> None:
    data = build_record_zip(_record(), cluster_id="cluster-1", payloads=_payloads())
    broken = _rewrite(data, remove="results.json")

    with pytest.raises(RecordZipError):
        validate_record_zip(broken)


def test_checksum_tamper_is_rejected() -> None:
    data = build_record_zip(_record(), cluster_id="cluster-1", payloads=_payloads())
    tampered = _rewrite(data, replace={"results.json": b'{"outcome":"PASS"}'})

    with pytest.raises(RecordZipError):
        validate_record_zip(tampered)


def test_zip_slip_path_is_rejected() -> None:
    payloads = _payloads()
    payloads["../escape.json"] = "{}"

    with pytest.raises(RecordZipError):
        build_record_zip(_record(), cluster_id="cluster-1", payloads=payloads)


# ---- audit records ----------------------------------------------------------
def test_audit_zip_is_explicitly_not_executed() -> None:
    record = _record(
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    data = build_audit_record_zip(record, cluster_id="cluster-1", payloads=_audit_payloads())

    validation = validate_record_zip(data)
    assert validation.manifest["executed"] is False
    assert validation.manifest["coverage"] == "NONE"
    assert validation.manifest["audit_id"] == "audit-1"
    assert validation.manifest["task_id"] is None


def test_audit_builder_rejects_executed_record() -> None:
    with pytest.raises(RecordZipError):
        build_audit_record_zip(_record(), cluster_id="cluster-1", payloads=_payloads())


def test_audit_zip_cannot_claim_execution() -> None:
    record = _record(
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    payloads = _audit_payloads()
    payloads["results.json"] = '{"outcome":"PASS","executed":true}'
    data = build_record_zip(record, cluster_id="cluster-1", payloads=payloads)

    with pytest.raises(RecordZipError):
        validate_record_zip(data)


# ---- manifest contract ------------------------------------------------------
def test_manifest_files_exclude_manifest_and_checksums() -> None:
    data = build_record_zip(_record(), cluster_id="cluster-1", payloads=_payloads())
    validation = validate_record_zip(data)

    assert "manifest.json" not in validation.manifest["files"]
    assert "checksums.sha256" not in validation.manifest["files"]
    assert "candidate/source/kernel.cpp" in validation.manifest["files"]


def test_invalid_manifest_json_is_rejected() -> None:
    data = build_record_zip(_record(), cluster_id="cluster-1", payloads=_payloads())
    broken = _rewrite(data, replace={"manifest.json": b"not-json"})

    with pytest.raises(RecordZipError):
        validate_record_zip(broken)


def test_record_id_mismatch_is_rejected() -> None:
    data = build_record_zip(_record(), cluster_id="cluster-1", payloads=_payloads())

    with pytest.raises(RecordZipError):
        validate_record_zip(data, expected_record_id="other")


def test_audit_fixture_does_not_use_test_record_error() -> None:
    record = _record(
        executed=False,
        task_id=None,
        job_id=None,
        audit_id="audit-1",
        coverage=Coverage.NONE,
        outcome=Outcome.CANCELLED,
    )
    assert record.is_audit
    assert json.loads(_audit_payloads()["results.json"])["executed"] is False
    with pytest.raises(RecordError):
        _record(executed=False, task_id=None, job_id=None, audit_id=None)

"""Deterministic TestRecord zip builder and public archive contract."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping

from justkernel.testing.record import TestRecord
from justkernel.testing.record_zip_format import (
    REQUIRED_FILES,
    RESERVED_FILES,
    SCHEMA,
    SOURCE_PREFIX,
    RecordZipError,
    RecordZipValidation,
    checksum_lines,
    digest,
    json_bytes,
    validate_name,
)
from justkernel.testing.record_zip_validation import validate_record_zip

__all__ = [
    "RecordZipError",
    "RecordZipValidation",
    "build_audit_record_zip",
    "build_record_zip",
    "validate_record_zip",
]


def build_record_zip(
    record: TestRecord,
    *,
    cluster_id: str,
    payloads: Mapping[str, bytes | str],
    extra_manifest: Mapping[str, object] | None = None,
) -> bytes:
    if not cluster_id:
        raise RecordZipError("cluster_id must be non-empty")
    contents = _normalise_payloads(payloads)
    contents["README.md"] = _readme(record).encode("utf-8")
    manifest = _manifest(record, cluster_id, contents, extra_manifest)
    contents["manifest.json"] = json_bytes(manifest)
    contents["checksums.sha256"] = checksum_lines(contents)
    return _zip_bytes(contents)


def build_audit_record_zip(
    record: TestRecord,
    *,
    cluster_id: str,
    payloads: Mapping[str, bytes | str],
    extra_manifest: Mapping[str, object] | None = None,
) -> bytes:
    if not record.is_audit:
        raise RecordZipError("audit zip requires an audit record")
    return build_record_zip(
        record,
        cluster_id=cluster_id,
        payloads=payloads,
        extra_manifest=extra_manifest,
    )


def _normalise_payloads(payloads: Mapping[str, bytes | str]) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for name, value in payloads.items():
        validate_name(name)
        if name in RESERVED_FILES:
            raise RecordZipError(f"reserved file cannot be supplied: {name}")
        contents[name] = value.encode("utf-8") if isinstance(value, str) else value
    missing = REQUIRED_FILES - contents.keys() - RESERVED_FILES
    if missing:
        raise RecordZipError(f"missing required files: {sorted(missing)}")
    if not any(name.startswith(SOURCE_PREFIX) for name in contents):
        raise RecordZipError("zip requires at least one candidate source file")
    return contents


def _manifest(
    record: TestRecord,
    cluster_id: str,
    contents: Mapping[str, bytes],
    extra: Mapping[str, object] | None,
) -> dict[str, object]:
    manifest = dict(extra or {})
    manifest.update(
        {
            "schema": SCHEMA,
            "record_id": record.id.value,
            "cluster_id": cluster_id,
            "candidate_id": record.candidate_id.value,
            "task_id": record.task_id.value if record.task_id else None,
            "job_id": record.job_id,
            "audit_id": record.audit_id,
            "kind": record.kind.value,
            "skill": {
                "name": record.skill_ref.name,
                "version": record.skill_ref.version,
                "digest": record.skill_ref.digest.value,
            },
            "backend": record.backend,
            "outcome": record.outcome.value,
            "executed": record.executed,
            "coverage": record.coverage.value,
            "created_at": record.created_at,
            "environment": dict(record.environment.values),
            "files": {name: digest(value) for name, value in contents.items()},
        }
    )
    return manifest


def _readme(record: TestRecord) -> str:
    status = "EXECUTED" if record.executed else "NOT EXECUTED"
    reason = record.summary or "no summary"
    return (
        f"# TestRecord {record.id.value}\n\n"
        f"- kind: {record.kind.value}\n"
        f"- outcome: {record.outcome.value}\n"
        f"- coverage: {record.coverage.value}\n"
        f"- status: {status}\n"
        f"- reason: {reason}\n"
    )


def _zip_bytes(contents: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(contents):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, contents[name])
    return buffer.getvalue()

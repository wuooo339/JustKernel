"""Fail-closed validation for TestRecord zip archives."""

from __future__ import annotations

import json
from collections.abc import Mapping

from justkernel.testing.record_zip_format import (
    JSON_FILES,
    SCHEMA,
    RecordZipError,
    RecordZipValidation,
    digest,
    parse_checksums,
    parse_manifest,
    read_files,
    require_members,
)


def validate_record_zip(
    data: bytes,
    *,
    expected_record_id: str | None = None,
) -> RecordZipValidation:
    files = read_files(data)
    require_members(files)
    manifest = parse_manifest(files["manifest.json"])
    checksums = parse_checksums(files["checksums.sha256"])
    _validate_checksums(files, checksums)
    _validate_manifest(manifest, expected_record_id)
    _validate_manifest_files(manifest, checksums)
    _validate_semantics(manifest, files)
    return RecordZipValidation(
        record_id=str(manifest["record_id"]),
        manifest=manifest,
        files={name: digest(content) for name, content in files.items()},
    )


def _validate_manifest(manifest: Mapping[str, object], expected: str | None) -> None:
    if manifest.get("schema") != SCHEMA:
        raise RecordZipError("manifest schema mismatch")
    record_id = manifest.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise RecordZipError("manifest record_id is required")
    if expected is not None and record_id != expected:
        raise RecordZipError("record id mismatch")
    if not isinstance(manifest.get("files"), dict):
        raise RecordZipError("manifest files must be an object")
    if not isinstance(manifest.get("executed"), bool):
        raise RecordZipError("manifest executed must be boolean")


def _validate_checksums(files: Mapping[str, bytes], checksums: Mapping[str, str]) -> None:
    expected = set(files) - {"checksums.sha256"}
    if set(checksums) != expected:
        raise RecordZipError("checksums do not cover exactly the archive files")
    for name, value in checksums.items():
        if digest(files[name]) != value:
            raise RecordZipError(f"checksum mismatch: {name}")


def _validate_manifest_files(
    manifest: Mapping[str, object],
    checksums: Mapping[str, str],
) -> None:
    expected = {
        name: value
        for name, value in checksums.items()
        if name not in {"manifest.json", "checksums.sha256"}
    }
    if manifest.get("files") != expected:
        raise RecordZipError("manifest.files does not match archive files")


def _validate_semantics(manifest: Mapping[str, object], files: Mapping[str, bytes]) -> None:
    for name in JSON_FILES:
        try:
            json.loads(files[name].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RecordZipError(f"{name} is invalid JSON") from error
    if manifest["executed"]:
        _validate_executed(manifest)
    else:
        _validate_audit(manifest)
    results = json.loads(files["results.json"].decode("utf-8"))
    _validate_results(manifest, results)


def _validate_executed(manifest: Mapping[str, object]) -> None:
    if not manifest.get("task_id") or not manifest.get("job_id"):
        raise RecordZipError("executed manifest requires task_id and job_id")
    if manifest.get("audit_id") is not None:
        raise RecordZipError("executed manifest must not have audit_id")
    if manifest.get("coverage") not in {"FULL", "SUBSET"}:
        raise RecordZipError("executed manifest requires FULL or SUBSET coverage")


def _validate_audit(manifest: Mapping[str, object]) -> None:
    if manifest.get("task_id") is not None or manifest.get("job_id") is not None:
        raise RecordZipError("audit manifest must not have task_id or job_id")
    if not manifest.get("audit_id"):
        raise RecordZipError("audit manifest requires audit_id")
    if manifest.get("coverage") != "NONE":
        raise RecordZipError("audit manifest requires NONE coverage")
    if manifest.get("outcome") not in {"CANCELLED", "UNKNOWN"}:
        raise RecordZipError("audit outcome must be CANCELLED or UNKNOWN")


def _validate_results(manifest: Mapping[str, object], results: object) -> None:
    if not isinstance(results, dict):
        raise RecordZipError("results must be an object")
    if results.get("executed") is not manifest["executed"]:
        raise RecordZipError("results.executed disagrees with manifest")
    if "outcome" in results and results["outcome"] != manifest.get("outcome"):
        raise RecordZipError("results.outcome disagrees with manifest")

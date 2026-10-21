"""Shared TestRecord zip format constants and low-level readers."""

from __future__ import annotations

import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError

SCHEMA = "justkernel.test_record.v1"
SOURCE_PREFIX = "candidate/source/"
RESERVED_FILES = frozenset({"README.md", "manifest.json", "checksums.sha256"})
REQUIRED_FILES = frozenset(
    {
        "README.md",
        "manifest.json",
        "checksums.sha256",
        "task.json",
        "context.json",
        "operator-spec.json",
        "candidate/diff.patch",
        "candidate/source.sha256",
        "skill/SKILL.md",
        "skill/metadata.json",
        "cases.json",
        "config.json",
        "environment.json",
        "commands.log",
        "stdout.log",
        "stderr.log",
        "results.json",
        "metrics.json",
        "provenance.json",
    }
)
JSON_FILES = (
    "task.json",
    "context.json",
    "operator-spec.json",
    "skill/metadata.json",
    "cases.json",
    "config.json",
    "environment.json",
    "results.json",
    "metrics.json",
    "provenance.json",
)
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class RecordZipError(JustKernelError):
    code = ErrorCode.INVALID_TEST_RECORD


@dataclass(frozen=True, slots=True)
class RecordZipValidation:
    record_id: str
    manifest: Mapping[str, object]
    files: Mapping[str, str]


def validate_name(name: str) -> None:
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise RecordZipError(f"unsafe archive path: {name!r}")
    if any(part in {"", ".", ".."} for part in name.split("/")):
        raise RecordZipError(f"unsafe archive path: {name!r}")


def read_files(data: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = [info.filename for info in archive.infolist()]
        if len(names) != len(set(names)):
            raise RecordZipError("duplicate zip entries")
        files: dict[str, bytes] = {}
        for info in archive.infolist():
            validate_name(info.filename)
            if info.is_dir():
                raise RecordZipError(f"directories are not allowed: {info.filename}")
            files[info.filename] = archive.read(info)
        return files
    except (zipfile.BadZipFile, OSError) as error:
        raise RecordZipError("zip is unreadable") from error


def require_members(files: Mapping[str, bytes]) -> None:
    missing = REQUIRED_FILES - files.keys()
    if missing:
        raise RecordZipError(f"missing required files: {sorted(missing)}")
    if not any(name.startswith(SOURCE_PREFIX) for name in files):
        raise RecordZipError("zip requires at least one candidate source file")


def parse_manifest(data: bytes) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecordZipError("manifest.json is invalid") from error
    if not isinstance(value, dict):
        raise RecordZipError("manifest must be an object")
    return value


def parse_checksums(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise RecordZipError("checksums are not UTF-8") from error
    checksums: dict[str, str] = {}
    for line in lines:
        if not line:
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not HEX_DIGEST.fullmatch(parts[0]):
            raise RecordZipError("invalid checksum line")
        name = parts[1]
        validate_name(name)
        if name in checksums:
            raise RecordZipError(f"duplicate checksum: {name}")
        checksums[name] = parts[0]
    return checksums


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def checksum_lines(contents: Mapping[str, bytes]) -> bytes:
    lines = [f"{digest(value)}  {name}" for name, value in sorted(contents.items())]
    return ("\n".join(lines) + "\n").encode("utf-8")

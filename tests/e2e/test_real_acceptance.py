from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from justkernel.testing.record_zip import validate_record_zip

ENV_KEY = "JUSTKERNEL_REAL_ACCEPTANCE_DIR"
SCHEMA = "justkernel.real_acceptance.v1"


def _evidence_dir() -> Path:
    raw = os.environ.get(ENV_KEY)
    if not raw:
        pytest.skip(f"{ENV_KEY} is not set; real CANN/model evidence was not supplied")
    path = Path(raw)
    if not path.is_dir():
        pytest.fail(f"{ENV_KEY} does not point to a directory: {path}")
    return path


def test_real_cann_and_model_evidence() -> None:
    bundle = _evidence_dir()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == SCHEMA
    assert manifest["real_model"] is True
    assert manifest["real_cann"] is True
    assert manifest["backend"] != "cann-simulation"
    assert manifest["model_provider"] not in {"fake", "simulation"}
    for field in (
        "model_name",
        "model_version",
        "soc",
        "cann_version",
        "device",
        "record_id",
        "artifact_digest",
    ):
        assert manifest[field], field

    archive = (bundle / "final-record.zip").read_bytes()
    assert hashlib.sha256(archive).hexdigest() == manifest["artifact_digest"]
    validation = validate_record_zip(archive, expected_record_id=manifest["record_id"])
    assert validation.manifest["executed"] is True
    assert validation.manifest["coverage"] == "FULL"
    assert validation.manifest["outcome"] == "PASS"
    assert validation.manifest["backend"] == manifest["backend"]
    report = json.loads((bundle / manifest["report"]).read_text(encoding="utf-8"))
    assert report.get("cluster_id")

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "src" / "justkernel" / "web" / "demo" / "fixture.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_demo_fixture_is_synthetic_and_ordered() -> None:
    fixture = _fixture()
    meta = fixture["meta"]
    events = fixture["events"]

    assert meta["mode"] == "demo"
    assert meta["source"] == "synthetic"
    assert meta["model_calls"] == 0
    assert meta["device_calls"] == 0
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert len({event["id"] for event in events}) == len(events)


def test_demo_replay_is_deterministic_without_models_or_devices() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for demo replay")

    fixture_url = (ROOT / "src" / "justkernel" / "web" / "demo" / "fixture.js").as_uri()
    script = (
        f"import {{ DEMO_STATE, DEMO_EVENTS }} from {json.dumps(fixture_url)};"
        "console.log(JSON.stringify({state: DEMO_STATE, count: DEMO_EVENTS.length}));"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    state = payload["state"]

    assert payload["count"] == 17
    assert state["clusters"]["demo-cluster"]["state"] == "COMPLETED"
    assert state["clusters"]["demo-cluster"]["best_candidate_id"] == "demo-candidate-2"
    assert state["records"]["demo-record-1"]["outcome"] == "FAIL"
    assert state["bestSelections"]["demo-selection"]["state"] == "VALIDATED"

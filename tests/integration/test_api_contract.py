from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict

import pytest
from fastapi.testclient import TestClient

from justkernel.cluster.errors import ClusterError
from justkernel.platform.http.app import create_app
from justkernel.platform.http.dtos import (
    AgentView,
    BoardPostView,
    CandidateView,
    ClusterView,
    QueueView,
    SkillView,
)
from justkernel.platform.http.dtos import TestRecordView as RecordView
from justkernel.platform.http.errors import IdempotencyConflictError
from justkernel.platform.http.idempotency import IdempotencyStore, fingerprint_bytes


# ---- helpers ----------------------------------------------------------------
def _client() -> tuple[TestClient, list[dict[str, object]]]:
    app = create_app()
    calls: list[dict[str, object]] = []

    @app.post("/api/v1/test-write")
    def write(payload: dict[str, object]) -> dict[str, object]:
        calls.append(payload)
        return {"accepted": True, "payload": payload}

    @app.get("/api/v1/test-error")
    def fail() -> None:
        raise ClusterError("not running")

    @app.post("/api/v1/test-required")
    def required(value: int) -> int:
        return value

    return TestClient(app), calls


# ---- skeleton ---------------------------------------------------------------
def test_health_endpoint() -> None:
    client, _ = _client()

    response = client.get("/api/v1/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"]


def test_domain_error_is_problem_json() -> None:
    client, _ = _client()

    response = client.get("/api/v1/test-error")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "invalid_cluster_transition"
    assert body["status"] == 409
    assert body["title"]


def test_request_validation_uses_stable_problem_code() -> None:
    client, _ = _client()

    response = client.post("/api/v1/test-required")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "request.invalid"


# ---- idempotency ------------------------------------------------------------
def test_idempotent_post_replays_and_conflicts() -> None:
    client, calls = _client()
    headers = {"Idempotency-Key": "key-1"}

    first = client.post("/api/v1/test-write", json={"value": 1}, headers=headers)
    second = client.post("/api/v1/test-write", json={"value": 1}, headers=headers)
    conflict = client.post("/api/v1/test-write", json={"value": 2}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert calls == [{"value": 1}]
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")
    assert conflict.json()["code"] == "idempotency.conflict"


def test_idempotency_store_fingerprints() -> None:
    store = IdempotencyStore()
    fingerprint = fingerprint_bytes(b'{"x":1}')

    assert store.begin("key", fingerprint) is None
    store.put("key", fingerprint, 200, b'{"ok":true}', "application/json")
    assert store.begin("key", fingerprint).body == b'{"ok":true}'
    with pytest.raises(IdempotencyConflictError):
        store.begin("key", fingerprint_bytes(b'{"x":2}'))
    with pytest.raises(IdempotencyConflictError):
        store.begin("", fingerprint)


# ---- DTOs -------------------------------------------------------------------
def test_read_model_dtos_are_immutable_and_serializable() -> None:
    skill = SkillView(name="tester", version="1", digest="a" * 64)
    cluster = ClusterView(
        id="c1",
        operator_id="op",
        supervisor_id="s1",
        state="RUNNING",
        phase="BOOTSTRAPPING",
        start_mode="GENERATE",
        operator_spec_digest="b" * 64,
        baseline_candidate_id=None,
        continued_from_cluster_id=None,
        max_agents=100,
        active_agents=3,
        best_candidate_id=None,
        report_id=None,
        created_at=0,
        closed_at=None,
    )
    agent = AgentView(
        id="a1",
        role="MENTOR",
        mentor_id=None,
        model_profile="model",
        skills=(skill,),
        state="IDLE",
        current_task_id=None,
        created_at=0,
        closed_at=None,
    )
    candidate = CandidateView(
        id="cand",
        parent_id=None,
        direction_id="d1",
        author_agent_id=None,
        author_principal="system",
        evaluation={},
        source_digest="c" * 64,
        metrics={},
        record_count=0,
        created_at=0,
    )
    record = RecordView(
        id="r1",
        candidate_id="cand",
        kind="TEST",
        skill=skill,
        backend="cann-simulation",
        outcome="PASS",
        executed=True,
        coverage="FULL",
        operator_spec_digest="b" * 64,
        case_pack_digest="d" * 64,
        evaluation_policy_digest="e" * 64,
        metrics={},
        environment={"soc": "Ascend910B4"},
        artifact_digest="f" * 64,
        created_at=0,
    )
    board = BoardPostView(
        id="p1",
        seq=1,
        board="mentor",
        topic="direction",
        author_agent_id="a1",
        payload={},
        created_at=0,
    )
    queue = QueueView(devices=(), queued=(), leased=())

    assert asdict(cluster)["state"] == "RUNNING"
    assert asdict(agent)["skills"][0]["name"] == "tester"
    assert asdict(candidate)["record_count"] == 0
    assert asdict(record)["artifact_digest"] == "f" * 64
    assert asdict(board)["board"] == "mentor"
    assert asdict(queue)["devices"] == ()

    with pytest.raises(FrozenInstanceError):
        cluster.state = "STOPPED"

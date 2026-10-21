from __future__ import annotations

from fastapi.testclient import TestClient

from justkernel.application.cluster_service import ClusterService
from justkernel.application.fakes import (
    FakeArtifactStore,
    FakeIds,
    FakeMessageBus,
    InMemoryAgentRepository,
    InMemoryCandidateRepository,
    InMemoryClusterRepository,
    InMemoryDirectionRepository,
    InMemoryReportRepository,
    InMemoryTaskRepository,
    InMemoryTestRecordRepository,
    InMemoryToolJobRepository,
)
from justkernel.cluster.operator_spec import OperatorRef
from justkernel.cluster.state import StartMode
from justkernel.comm.channels import Channel
from justkernel.platform.http.app import create_app
from justkernel.platform.http.context import ApiContext
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId


def _operator_ref() -> OperatorRef:
    return OperatorRef(
        operator_id="op-1",
        version="1",
        digest=Digest.from_text("spec"),
        artifact_ref="artifact://spec",
    )


def _client() -> tuple[TestClient, object, FakeMessageBus]:
    clusters = InMemoryClusterRepository()
    messages = FakeMessageBus()
    ids = FakeIds()
    service = ClusterService(clusters, ids)
    cluster = service.create_cluster(
        operator_id="op-1",
        supervisor_id=AgentId.generate(),
        operator_spec_ref=_operator_ref(),
        start_mode=StartMode.GENERATE,
        max_agents=6,
        created_at=0,
    )
    service.start_cluster(cluster.id)
    context = ApiContext(
        clusters=clusters,
        agents=InMemoryAgentRepository(),
        tasks=InMemoryTaskRepository(),
        candidates=InMemoryCandidateRepository(),
        records=InMemoryTestRecordRepository(),
        jobs=InMemoryToolJobRepository(),
        directions=InMemoryDirectionRepository(),
        reports=InMemoryReportRepository(),
        messages=messages,
        artifacts=FakeArtifactStore(),
        cluster_service=service,
        now_ms=lambda: 0,
    )
    return TestClient(create_app(context=context)), cluster, messages


def test_agent_card_exposes_only_cluster_skills() -> None:
    client, cluster, _ = _client()

    card = client.get(f"/api/v1/a2a/agent-card?cluster_id={cluster.id.value}")

    assert card.status_code == 200
    assert [skill["id"] for skill in card.json()["skills"]] == [
        "cluster-status",
        "cluster-message",
    ]
    assert "worker" not in str(card.json()).lower()
    assert card.json()["state"] == "RUNNING"


def test_a2a_status_is_cluster_summary_only() -> None:
    client, cluster, _ = _client()

    response = client.post(
        "/api/v1/a2a/messages",
        json={"action": "status", "cluster_id": cluster.id.value},
    )

    assert response.status_code == 200
    assert response.json()["cluster"]["state"] == "RUNNING"
    assert "agents" not in response.json()
    assert response.json()["directions"] == 0


def test_external_message_is_idempotent_and_not_worker_channel() -> None:
    client, cluster, messages = _client()
    payload = {
        "action": "message",
        "cluster_id": cluster.id.value,
        "topic": "direction",
        "message": "please explore memory",
        "delivery_id": "delivery-1",
    }

    first = client.post("/api/v1/a2a/messages", json=payload)
    second = client.post("/api/v1/a2a/messages", json=payload)

    assert first.status_code == 200
    assert first.json() == {"delivery_id": "delivery-1", "duplicate": False}
    assert second.json() == {"delivery_id": "delivery-1", "duplicate": True}
    stored = messages.messages(Channel.external())
    assert len(stored) == 1
    assert stored[0].channel == Channel.external()
    assert stored[0].sender.kind == "human"
    assert stored[0].type.value == "ExternalMessage"
    assert messages.messages(Channel.worker(AgentId.generate(), AgentId.generate())) == ()


def test_a2a_cannot_target_worker_or_board_channel() -> None:
    client, cluster, messages = _client()

    for channel in ("worker:abc:def", "mentor_board"):
        response = client.post(
            "/api/v1/a2a/messages",
            json={
                "action": "message",
                "cluster_id": cluster.id.value,
                "channel": channel,
                "topic": "direction",
                "message": "blocked",
                "delivery_id": "delivery-" + channel,
            },
        )
        assert response.status_code == 403
        assert response.json()["code"] == "acl.denied"
    assert messages.messages() == ()

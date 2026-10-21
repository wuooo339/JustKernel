from __future__ import annotations

import json

from fastapi.testclient import TestClient

from justkernel.application.fakes import (
    FakeArtifactStore,
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
from justkernel.platform.http.app import create_app
from justkernel.platform.http.context import ApiContext
from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.events import EventStore
from justkernel.platform.persistence.migrations import apply_migrations
from justkernel.shared.events import DomainEvent, EventType
from justkernel.shared.ids import ClusterId, EventId
from justkernel.shared.principal import Principal


# ---- fixture ----------------------------------------------------------------
def _client() -> tuple[TestClient, EventStore]:
    connection = connect(":memory:", check_same_thread=False)
    apply_migrations(connection)
    store = EventStore(connection)
    cluster = ClusterId.generate()
    for index in range(3):
        store.append(
            DomainEvent(
                id=EventId.generate(),
                cluster_id=cluster,
                type=EventType.AGENT_IDLE,
                event_version=1,
                aggregate_type="agent",
                aggregate_id=f"agent-{index}",
                aggregate_version=0,
                actor=Principal.system(),
                occurred_at=index,
                payload={"index": index},
            )
        )
    context = ApiContext(
        clusters=InMemoryClusterRepository(),
        agents=InMemoryAgentRepository(),
        tasks=InMemoryTaskRepository(),
        candidates=InMemoryCandidateRepository(),
        records=InMemoryTestRecordRepository(),
        jobs=InMemoryToolJobRepository(),
        directions=InMemoryDirectionRepository(),
        reports=InMemoryReportRepository(),
        messages=FakeMessageBus(),
        artifacts=FakeArtifactStore(),
        events=store,
    )
    return TestClient(create_app(context=context)), store


def _parse_sse(text: str) -> list[tuple[int, dict[str, object]]]:
    events: list[tuple[int, dict[str, object]]] = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        event_id = 0
        data: dict[str, object] = {}
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = int(line[4:])
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((event_id, data))
    return events


# ---- pagination -------------------------------------------------------------
def test_events_pagination_and_cursor() -> None:
    client, _ = _client()

    first = client.get("/api/v1/events?limit=2")
    second = client.get("/api/v1/events?after=2&limit=2")

    assert first.status_code == 200
    assert [item["seq"] for item in first.json()["events"]] == [1, 2]
    assert first.json()["next_after"] == 2
    assert [item["seq"] for item in second.json()["events"]] == [3]
    assert second.json()["next_after"] == 3


# ---- SSE replay -------------------------------------------------------------
def test_sse_replay_uses_last_event_id() -> None:
    client, _ = _client()

    response = client.get(
        "/api/v1/events/stream?after=0",
        headers={"Last-Event-ID": "1"},
    )
    events = _parse_sse(response.text)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [event_id for event_id, _ in events] == [2, 3]
    assert events[0][1]["type"] == "agent.idle"
    assert events[0][1]["payload"] == {"index": 1}


def test_sse_after_query_and_invalid_cursor() -> None:
    client, _ = _client()

    response = client.get("/api/v1/events/stream?after=2")
    events = _parse_sse(response.text)
    assert [event_id for event_id, _ in events] == [3]

    invalid = client.get(
        "/api/v1/events/stream",
        headers={"Last-Event-ID": "not-an-int"},
    )
    assert invalid.status_code == 422
    assert invalid.headers["content-type"].startswith("application/problem+json")
    assert invalid.json()["code"] == "request.invalid"


def test_event_payload_is_json_not_db_row() -> None:
    client, _ = _client()

    response = client.get("/api/v1/events?limit=1")
    event = response.json()["events"][0]

    assert set(event) == {"seq", "id", "cluster_id", "type", "occurred_at", "payload"}
    assert "payload_json" not in event

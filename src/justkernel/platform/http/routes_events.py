"""Event pagination and SSE replay routes."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse

from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.dtos import EventPage, EventView
from justkernel.platform.http.errors import ApiError
from justkernel.platform.persistence.events import EventStore
from justkernel.shared.events import DomainEvent


def _event_view(seq: int, event: DomainEvent) -> EventView:
    return EventView(
        seq=seq,
        id=event.id.value,
        cluster_id=event.cluster_id.value,
        type=event.type.value,
        occurred_at=event.occurred_at,
        payload=dict(event.payload),
    )


def _store(ctx: ApiContext) -> EventStore:
    if ctx.events is None:
        raise ApiError("event store is not configured")
    return ctx.events


def _after(request: Request, query_after: int) -> int:
    header = request.headers.get("Last-Event-ID")
    if header is None:
        return query_after
    try:
        value = int(header)
    except ValueError as error:
        raise ApiError("Last-Event-ID must be an integer") from error
    if value < 0:
        raise ApiError("Last-Event-ID must be non-negative")
    return value


def _page(store: EventStore, after: int, limit: int) -> EventPage:
    records = store.read_after_with_seq(after, limit)
    events = tuple(_event_view(seq, event) for seq, event in records)
    next_after = records[-1][0] if records else after
    return EventPage(events=events, next_after=next_after)


def _sse_data(seq: int, event: DomainEvent) -> str:
    payload = {
        "seq": seq,
        "id": event.id.value,
        "cluster_id": event.cluster_id.value,
        "type": event.type.value,
        "occurred_at": event.occurred_at,
        "payload": dict(event.payload),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sse_stream(store: EventStore, after: int) -> Iterator[str]:
    for seq, event in store.read_after_with_seq(after, 200):
        yield f"id: {seq}\nevent: message\ndata: {_sse_data(seq, event)}\n\n"


def register_event_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/events")
    def list_events(
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ) -> EventPage:
        return _page(_store(ctx), after, limit)

    @app.get("/api/v1/events/stream")
    def stream_events(request: Request, after: int = Query(default=0, ge=0)) -> StreamingResponse:
        cursor = _after(request, after)
        return StreamingResponse(
            _sse_stream(_store(ctx), cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

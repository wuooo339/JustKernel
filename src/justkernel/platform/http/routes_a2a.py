"""A2A cluster gateway: card, status and restricted external messages."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from justkernel.comm.channels import Channel
from justkernel.comm.errors import AccessDeniedError
from justkernel.comm.message import Message, MessageType
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.errors import ApiError
from justkernel.platform.http.routes_common import cluster, cluster_view
from justkernel.shared.ids import MessageId
from justkernel.shared.principal import Principal


class A2aMessageBody(BaseModel):
    action: Literal["status", "message"]
    cluster_id: str
    topic: str | None = None
    message: str | None = None
    delivery_id: str | None = None
    channel: str | None = None


def _card(cluster_id: str, state: object) -> dict[str, object]:
    return {
        "name": f"justkernel-{cluster_id}",
        "description": "JustKernel single-operator exploration cluster",
        "capabilities": ["cluster-status", "cluster-message"],
        "skills": [
            {
                "id": "cluster-status",
                "description": "Read cluster state, phase, baseline and best summary.",
            },
            {
                "id": "cluster-message",
                "description": "Send an idempotent external topic message to the cluster.",
            },
        ],
        "state": state,
    }


def _status(ctx: ApiContext, cluster_id: str) -> dict[str, object]:
    item = cluster(ctx, cluster_id)
    return {
        "cluster": cluster_view(ctx, item),
        "directions": len(ctx.directions.list_by_cluster(item.id)),
        "candidates": len(ctx.candidates.list_by_cluster(item.id)),
    }


def _publish(ctx: ApiContext, body: A2aMessageBody) -> dict[str, object]:
    if body.channel not in (None, "external"):
        raise AccessDeniedError("A2A cannot write worker or board channels")
    if not body.topic or not body.message or not body.delivery_id:
        raise ApiError("message action requires topic, message and delivery_id")
    if body.delivery_id in ctx.a2a_deliveries:
        return {"delivery_id": body.delivery_id, "duplicate": True}
    cluster_obj = cluster(ctx, body.cluster_id)
    seq = len(ctx.messages.messages(Channel.external())) + 1
    ctx.messages.publish(
        Message(
            id=MessageId.generate(),
            cluster_id=cluster_obj.id,
            seq=seq,
            channel=Channel.external(),
            type=MessageType.EXTERNAL_MESSAGE,
            sender=Principal.human(),
            created_at=ctx.now_ms(),
            payload={
                "delivery_id": body.delivery_id,
                "topic": body.topic,
                "message": body.message,
            },
        )
    )
    ctx.a2a_deliveries.add(body.delivery_id)
    return {"delivery_id": body.delivery_id, "duplicate": False}


def register_a2a_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/a2a/agent-card")
    def agent_card(cluster_id: str) -> dict[str, object]:
        return _card(cluster_id, cluster(ctx, cluster_id).state.value)

    @app.get("/api/v1/a2a/status")
    def status(cluster_id: str) -> dict[str, object]:
        return _status(ctx, cluster_id)

    @app.post("/api/v1/a2a/messages")
    def message(body: A2aMessageBody) -> dict[str, object]:
        if body.action == "status":
            return _status(ctx, body.cluster_id)
        return _publish(ctx, body)

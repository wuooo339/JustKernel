"""Report, board, message and hardware read routes."""

from __future__ import annotations

from fastapi import FastAPI

from justkernel.comm.channels import Channel
from justkernel.comm.message import Message
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.dtos import MessageView, QueueView, ReportView
from justkernel.platform.http.routes_common import cluster, report, report_view


def _message_view(message: Message) -> MessageView:
    return MessageView(
        id=message.id.value,
        seq=message.seq,
        channel=message.channel.name,
        type=message.type.value,
        sender=str(message.sender),
        recipient=str(message.recipient) if message.recipient else None,
        payload=dict(message.payload),
        created_at=message.created_at,
    )


def register_report_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/clusters/{cluster_id}/report")
    def get_report(cluster_id: str) -> ReportView:
        return report_view(report(ctx, cluster(ctx, cluster_id)))


def register_board_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/clusters/{cluster_id}/board/mentor")
    def mentor_board(cluster_id: str) -> list[MessageView]:
        cluster(ctx, cluster_id)
        return [_message_view(message) for message in ctx.messages.messages(Channel.mentor_board())]

    @app.get("/api/v1/clusters/{cluster_id}/board/consultant")
    def consultant_board(cluster_id: str) -> list[MessageView]:
        cluster(ctx, cluster_id)
        return [
            _message_view(message) for message in ctx.messages.messages(Channel.consultant_board())
        ]


def register_message_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/messages")
    def messages(channel: str | None = None) -> list[MessageView]:
        parsed = Channel.parse(channel) if channel else None
        return [_message_view(message) for message in ctx.messages.messages(parsed)]


def register_hardware_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/hardware/queue")
    def hardware_queue() -> QueueView:
        if ctx.hardware is None:
            return QueueView(devices=(), queued=(), leased=())
        status = ctx.hardware.status()
        queued = tuple(
            {
                "queue_id": item.queue_id,
                "cluster_id": item.cluster_id,
                "task_id": item.task_id,
                "job_id": item.job_id,
                "device_id": item.device_id,
                "purpose": item.purpose,
                "priority": item.priority,
            }
            for item in status.queued
        )
        leased: tuple[dict[str, object], ...] = ()
        if status.active_lease is not None:
            lease = status.active_lease
            leased = (
                {
                    "lease_id": lease.lease_id,
                    "device_id": lease.device_id,
                    "task_id": lease.task_id,
                    "job_id": lease.job_id,
                    "fencing_token": lease.fencing_token,
                    "expires_at": lease.expires_at,
                },
            )
        return QueueView(devices=(), queued=queued, leased=leased)

"""Cluster read and lifecycle routes."""

from __future__ import annotations

from fastapi import FastAPI

from justkernel.application.cluster_service import ClusterService
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.errors import ApiError
from justkernel.platform.http.request_models import ClusterCreateBody
from justkernel.platform.http.routes_common import cluster, cluster_view
from justkernel.shared.ids import ClusterId


def _service(ctx: ApiContext) -> ClusterService:
    if ctx.cluster_service is None:
        raise ApiError("cluster lifecycle service is not configured")
    return ctx.cluster_service


def register_cluster_read_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/clusters/{cluster_id}")
    def get_cluster(cluster_id: str) -> object:
        return cluster_view(ctx, cluster(ctx, cluster_id))

    @app.get("/api/v1/clusters/{cluster_id}/graph")
    def get_graph(cluster_id: str) -> dict[str, object]:
        item = cluster(ctx, cluster_id)
        return {
            "cluster": cluster_view(ctx, item),
            "agents": [agent.id.value for agent in ctx.agents.list_by_cluster(item.id)],
            "tasks": [task.id.value for task in ctx.tasks.list_by_cluster(item.id)],
            "candidates": [
                candidate.id.value for candidate in ctx.candidates.list_by_cluster(item.id)
            ],
        }


def register_cluster_command_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.post("/api/v1/clusters", status_code=201)
    def create_cluster(payload: ClusterCreateBody) -> object:
        if ctx.start_cluster is None:
            raise ApiError("cluster start service is not configured")
        started = ctx.start_cluster.start(payload.to_start_request())
        return cluster_view(ctx, started.cluster)

    @app.post("/api/v1/clusters/{cluster_id}/pause")
    def pause(cluster_id: str) -> object:
        service = _service(ctx)
        return cluster_view(ctx, service.pause_cluster(ClusterId(cluster_id)))

    @app.post("/api/v1/clusters/{cluster_id}/resume")
    def resume(cluster_id: str) -> object:
        service = _service(ctx)
        return cluster_view(ctx, service.resume_cluster(ClusterId(cluster_id)))

    @app.post("/api/v1/clusters/{cluster_id}/converge")
    def converge(cluster_id: str) -> object:
        service = _service(ctx)
        return cluster_view(ctx, service.converge_cluster(ClusterId(cluster_id)))

    @app.post("/api/v1/clusters/{cluster_id}/stop")
    def stop(cluster_id: str, reason: str = "requested") -> object:
        service = _service(ctx)
        return cluster_view(
            ctx,
            service.stop_cluster(ClusterId(cluster_id), reason, ctx.now_ms()),
        )

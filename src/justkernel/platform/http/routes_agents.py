"""Agent and direction read routes."""

from __future__ import annotations

from fastapi import FastAPI

from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.routes_common import (
    agent,
    agent_view,
    cluster,
    direction_view,
)


def register_agent_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/clusters/{cluster_id}/agents")
    def list_agents(cluster_id: str) -> list[object]:
        item = cluster(ctx, cluster_id)
        return [agent_view(agent) for agent in ctx.agents.list_by_cluster(item.id)]

    @app.get("/api/v1/agents/{agent_id}")
    def get_agent(agent_id: str) -> object:
        return agent_view(agent(ctx, agent_id))

    @app.get("/api/v1/clusters/{cluster_id}/directions")
    def list_directions(cluster_id: str) -> list[object]:
        item = cluster(ctx, cluster_id)
        return [direction_view(direction) for direction in ctx.directions.list_by_cluster(item.id)]

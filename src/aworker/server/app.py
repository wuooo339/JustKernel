"""FastAPI application that serves the swarm over the A2A protocol."""

import logging

import uvicorn
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from fastapi import FastAPI

from aworker.config import Settings
from aworker.server.card import build_agent_card
from aworker.server.executor import SwarmAgentExecutor
from aworker.swarm.swarm import Swarm

logger = logging.getLogger(__name__)


# ---- create_app -------------------------------------------------------------
def create_app(settings: Settings, swarm: Swarm) -> FastAPI:
    """Build the FastAPI app that exposes ``swarm`` as a single A2A agent."""
    agent_card = build_agent_card(settings, swarm)
    request_handler = DefaultRequestHandler(
        agent_executor=SwarmAgentExecutor(swarm),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    app = FastAPI(title=settings.agent_name, version=settings.version)
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(agent_card),
        jsonrpc_routes=create_jsonrpc_routes(request_handler, rpc_url="/"),
    )
    return app


# ---- run_server -------------------------------------------------------------
def run_server(settings: Settings, swarm: Swarm) -> None:
    """Serve the swarm until the process is stopped."""
    app = create_app(settings, swarm)
    logger.info("serving %s at %s", settings.agent_name, settings.base_url)
    uvicorn.run(app, host=settings.host, port=settings.port)

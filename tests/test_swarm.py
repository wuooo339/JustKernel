"""Smoke tests for app assembly and the agent card."""

import pytest
from starlette.testclient import TestClient

from aworker.config import Settings
from aworker.server.app import create_app
from aworker.swarm import MemberAgent, Swarm


# ---- fixtures ---------------------------------------------------------------
@pytest.fixture
def settings() -> Settings:
    return Settings(host="127.0.0.1", port=9000, agent_name="TestSwarm")


@pytest.fixture
def swarm(settings: Settings) -> Swarm:
    swarm = Swarm(settings)
    swarm.add_member(
        MemberAgent(
            name="worker",
            description="does work",
            system_prompt="work",
            model=settings.model,
        )
    )
    return swarm


# ---- tests ------------------------------------------------------------------
def test_agent_card_lists_members(settings: Settings, swarm: Swarm) -> None:
    app = create_app(settings, swarm)

    with TestClient(app) as client:
        response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "TestSwarm"
    assert [skill["id"] for skill in card["skills"]] == ["worker"]


def test_swarm_enforces_max_members(settings: Settings) -> None:
    settings.max_members = 1
    swarm = Swarm(settings)
    swarm.add_member(MemberAgent(name="a", description="", system_prompt="", model=settings.model))

    with pytest.raises(ValueError):
        swarm.add_member(
            MemberAgent(name="b", description="", system_prompt="", model=settings.model)
        )

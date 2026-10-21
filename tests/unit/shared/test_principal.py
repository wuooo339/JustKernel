from __future__ import annotations

import pytest

from justkernel.shared.errors import InvalidPrincipalError
from justkernel.shared.ids import AgentId
from justkernel.shared.principal import Principal


# ---- construction and parsing ----------------------------------------------
def test_principal_round_trip() -> None:
    agent = AgentId.generate()
    principal = Principal.agent(agent)

    assert str(principal) == f"agent:{agent.value}"
    assert Principal.parse(str(principal)) == principal
    assert str(Principal.human()) == "human"
    assert str(Principal.system()) == "system"


def test_principal_rejects_invalid_values() -> None:
    invalid = [
        "agent:",
        "agent:" + "A" * 32,
        "agent:" + "a" * 31,
        "user",
        "human:x",
        "system:x",
    ]

    for value in invalid:
        with pytest.raises(InvalidPrincipalError):
            Principal.parse(value)


def test_principal_requires_agent_id_only_for_agent_kind() -> None:
    with pytest.raises(InvalidPrincipalError):
        Principal(kind="agent")
    with pytest.raises(InvalidPrincipalError):
        Principal(kind="human", agent_id=AgentId.generate())

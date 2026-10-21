from __future__ import annotations

from types import SimpleNamespace

from aworker.config import Settings
from aworker.server.card import build_agent_card


# ---- legacy A2A card --------------------------------------------------------
def test_agent_card_defaults_and_transport() -> None:
    settings = Settings(_env_file=None)
    card = build_agent_card(settings, SimpleNamespace(members=[]))

    assert card.name == "JustKernel"
    assert card.version == "0.2.0"
    assert card.capabilities.streaming is True
    assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
    assert str(card.supported_interfaces[0].protocol_version) == "1.0"
    assert card.skills == []

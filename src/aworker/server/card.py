"""Build the A2A agent card that describes the swarm to clients."""

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentInterface,
    AgentSkill,
)
from a2a.utils.constants import PROTOCOL_VERSION_1_0, TransportProtocol

from aworker.config import Settings
from aworker.server.extensions import LLM_PROVIDER_EXTENSION, WORKSPACE_EXTENSION
from aworker.swarm.member import MemberAgent
from aworker.swarm.swarm import Swarm


# ---- build_agent_card -------------------------------------------------------
def build_agent_card(settings: Settings, swarm: Swarm) -> AgentCard:
    """Describe the swarm as a single A2A agent, one skill per member."""
    return AgentCard(
        name=settings.agent_name,
        description=settings.agent_description,
        version=settings.version,
        supported_interfaces=[
            AgentInterface(
                url=settings.base_url,
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=True,
            extensions=[_llm_provider_extension(settings), _workspace_extension()],
        ),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[_member_skill(member) for member in swarm.members],
    )


# ---- _llm_provider_extension ------------------------------------------------
def _llm_provider_extension(settings: Settings) -> AgentExtension:
    return AgentExtension(
        uri=LLM_PROVIDER_EXTENSION,
        description=(
            "The swarm calls an external LLM inference service. Send the service "
            "endpoint and access key in the message metadata under this name."
        ),
        required=settings.require_llm_credential,
    )


# ---- _workspace_extension ---------------------------------------------------
def _workspace_extension() -> AgentExtension:
    return AgentExtension(
        uri=WORKSPACE_EXTENSION,
        description=(
            "Optional workspace the swarm may read and write within. Send a "
            "'root' directory path in the message metadata under this name."
        ),
        required=False,
    )


# ---- _member_skill ----------------------------------------------------------
def _member_skill(member: MemberAgent) -> AgentSkill:
    return AgentSkill(
        id=member.name,
        name=member.name,
        description=member.description,
        tags=["swarm-member"],
    )

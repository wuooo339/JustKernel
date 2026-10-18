"""The swarm: a dynamic set of members presented as a single agent.

The swarm keeps a registry of members and compiles a deepagents coordinator
that delegates work to them. Membership can change at runtime; the coordinator
is rebuilt lazily after any change. Externally the swarm behaves like one
agent, which is what the A2A server exposes.
"""

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from aworker.config import Settings
from aworker.messages import last_message_text
from aworker.models import build_chat_model
from aworker.server.client import send_text_message
from aworker.server.credentials import LLMCredential, MissingCredentialError
from aworker.server.extensions import LLM_PROVIDER_EXTENSION
from aworker.server.workspace import Workspace, build_workspace_backend
from aworker.swarm.member import MemberAgent

_COORDINATOR_PROMPT = """\
You are the coordinator of a swarm of specialist agents.

Break the user's request into sub-tasks and delegate each sub-task to the most
suitable specialist with the task tool. Review the specialists' results, resolve
conflicts, and produce one final answer for the user.

Do not expose internal delegation details; return only the final result.
"""


# ---- Swarm ------------------------------------------------------------------
class Swarm:
    """Registry of members plus the coordinator exposed to the outside world."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._members: dict[str, MemberAgent] = {}
        self._coordinator = None

    # ---- lifecycle ----------------------------------------------------------
    def add_member(self, member: MemberAgent) -> None:
        """Register a member and invalidate the compiled coordinator."""
        if len(self._members) >= self._settings.max_members and member.name not in self._members:
            raise ValueError(f"swarm reached max_members={self._settings.max_members}")
        self._members[member.name] = member
        self._coordinator = None

    def remove_member(self, name: str) -> None:
        """Remove a member and invalidate the compiled coordinator."""
        if self._members.pop(name, None) is not None:
            self._coordinator = None

    # ---- accessors ----------------------------------------------------------
    @property
    def members(self) -> tuple[MemberAgent, ...]:
        return tuple(self._members.values())

    # ---- execution ----------------------------------------------------------
    async def respond(
        self,
        prompt: str,
        thread_id: str,
        credential: LLMCredential | None = None,
        workspace: Workspace | None = None,
    ) -> str:
        """Let the coordinator answer ``prompt`` within a conversation thread.

        When ``credential`` is supplied, every agent calls the client's LLM
        endpoint with the client's key. When ``workspace`` is supplied, agents
        read and write files confined to the client's workspace root.
        """
        if credential is None and self._settings.require_llm_credential:
            raise MissingCredentialError(
                f"this agent requires the LLM provider extension '{LLM_PROVIDER_EXTENSION}'"
            )

        coordinator = self._coordinator_for(credential, workspace)
        state = await coordinator.ainvoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return last_message_text(state)

    # ---- helpers ------------------------------------------------------------
    def _coordinator_for(
        self,
        credential: LLMCredential | None,
        workspace: Workspace | None,
    ):
        """Return a coordinator, caching the client-extension-free default build."""
        if credential is None and workspace is None:
            if self._coordinator is None:
                self._coordinator = self._build_coordinator(self._settings.model)
            return self._coordinator

        model = build_chat_model(self._settings.model, credential)
        backend = build_workspace_backend(workspace) if workspace else None
        return self._build_coordinator(model, backend)

    def _build_coordinator(self, model, backend=None):
        return create_deep_agent(
            model=model,
            system_prompt=_COORDINATOR_PROMPT,
            subagents=[self._subagent_spec(member, model) for member in self._members.values()],
            backend=backend,
            name=self._settings.agent_name,
        )

    @staticmethod
    def _subagent_spec(member: MemberAgent, model: str | BaseChatModel) -> dict[str, object]:
        tools = list(member.tools)
        system_prompt = member.system_prompt
        if member.endpoint:
            endpoint = member.endpoint

            @tool
            async def delegate_a2a(task: str) -> str:
                """Send the task to this member's A2A endpoint and return its result."""
                return await send_text_message(endpoint, task)

            tools = [delegate_a2a]
            system_prompt += "\nExecute delegated work using delegate_a2a; report its real result."
        return {
            "name": member.name,
            "description": member.description,
            "system_prompt": system_prompt,
            "model": model if isinstance(model, BaseChatModel) else member.model,
            "tools": tools,
        }

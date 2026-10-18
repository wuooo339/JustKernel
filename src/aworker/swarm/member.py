"""A swarm member: a single deepagents agent.

A member is the unit of work inside the swarm. It wraps a compiled deepagents
graph and exposes a narrow async interface so the swarm can drive it without
knowing about LangGraph internals.
"""

from dataclasses import dataclass, field
from typing import Any

from deepagents import create_deep_agent

from aworker.messages import last_message_text


# ---- MemberAgent ------------------------------------------------------------
@dataclass
class MemberAgent:
    """A deepagents-backed agent that can be delegated work by the swarm."""

    name: str
    description: str
    system_prompt: str
    model: str
    tools: tuple[Any, ...] = ()
    endpoint: str | None = None
    _graph: Any = field(default=None, init=False, repr=False)

    # ---- lifecycle ----------------------------------------------------------
    def graph(self) -> Any:
        """Compile the deepagents graph once and reuse it."""
        if self._graph is None:
            self._graph = create_deep_agent(
                model=self.model,
                system_prompt=self.system_prompt,
                tools=list(self.tools) or None,
                name=self.name,
            )
        return self._graph

    # ---- execution ----------------------------------------------------------
    async def respond(self, prompt: str, thread_id: str) -> str:
        """Run the member on ``prompt`` within the given conversation thread."""
        state = await self.graph().ainvoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return last_message_text(state)

"""Bridge between the A2A request lifecycle and the swarm.

The executor turns one A2A request into a swarm run and publishes the result
back on the event queue. It owns all A2A message handling so the swarm itself
stays transport-agnostic.
"""

import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part

from aworker.server.credentials import extract_llm_credential
from aworker.server.workspace import extract_workspace
from aworker.swarm.swarm import Swarm

logger = logging.getLogger(__name__)


# ---- SwarmAgentExecutor -----------------------------------------------------
class SwarmAgentExecutor(AgentExecutor):
    """A2A executor that answers requests using the swarm coordinator.

    Each request produces a single agent message, so the executor runs in A2A
    message mode (immediate response) rather than streaming task updates.
    """

    def __init__(self, swarm: Swarm) -> None:
        self._swarm = swarm

    # ---- execution ----------------------------------------------------------
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        prompt = context.get_user_input()
        try:
            credential = extract_llm_credential(context.message)
            workspace = extract_workspace(context.message)
            answer = await self._swarm.respond(prompt, context.context_id, credential, workspace)
        except Exception as exc:  # noqa: BLE001 - report any swarm failure to the client
            logger.exception("swarm execution failed for task %s", context.task_id)
            await self._reply(context, event_queue, f"swarm failed: {exc}")
            return

        await self._reply(context, event_queue, answer)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Nothing to cancel: the executor answers each request immediately."""
        logger.debug("cancel requested for task %s but message mode has no task", context.task_id)

    # ---- helpers ------------------------------------------------------------
    async def _reply(self, context: RequestContext, event_queue: EventQueue, text: str) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(updater.new_agent_message([Part(text=text)]))

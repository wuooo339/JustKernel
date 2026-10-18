"""A2A client used by agents to talk to each other over the protocol.

Members inside a swarm and external callers use the same entry point: send a
text message to an A2A endpoint and collect the text that comes back.
"""

from uuid import uuid4

import httpx
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState


# ---- send_text_message ------------------------------------------------------
async def send_text_message(
    url: str,
    text: str,
    *,
    context_id: str | None = None,
) -> str:
    """Send ``text`` to the A2A agent at ``url`` and return its text reply."""
    # Model planning and CANN compilation can exceed HTTPX's five-second default.
    async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=12)) as http:
        client = await create_client(url, client_config=ClientConfig(httpx_client=http))
        try:
            request = SendMessageRequest(
                message=Message(
                    message_id=str(uuid4()),
                    context_id=context_id or "",
                    role=Role.ROLE_USER,
                    parts=[Part(text=text)],
                )
            )
            return await _collect_text(client, request)
        finally:
            await client.close()


# ---- _collect_text ----------------------------------------------------------
async def _collect_text(client, request: SendMessageRequest) -> str:
    """Drain the response stream and concatenate all text chunks."""
    chunks: list[str] = []
    async for response in client.send_message(request):
        payload = response.WhichOneof("payload")
        if payload == "message":
            chunks.append(_parts_text(response.message.parts))
        elif payload == "artifact_update":
            chunks.append(_parts_text(response.artifact_update.artifact.parts))
        elif payload in {"task", "status_update"}:
            status = getattr(response, payload).status
            if status.state == TaskState.TASK_STATE_COMPLETED and status.HasField("message"):
                chunks.append(_parts_text(status.message.parts))
            elif status.state in {TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED}:
                raise RuntimeError(_parts_text(status.message.parts) or "A2A task failed")
    return "".join(chunks)


# ---- _parts_text ------------------------------------------------------------
def _parts_text(parts) -> str:
    return "".join(part.text for part in parts if part.text)

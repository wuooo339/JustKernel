"""Helpers for reading text out of LangChain message state.

LangChain message ``content`` may be a plain string or a list of content
blocks. Swarm and server code only needs the textual output of an agent run,
so the conversion lives in one place.
"""

from typing import Any


# ---- message_text -----------------------------------------------------------
def message_text(message: Any) -> str:
    """Return the plain text of a single LangChain message."""
    content = getattr(message, "content", message)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(_block_text(block) for block in content)

    return str(content)


# ---- last_message_text ------------------------------------------------------
def last_message_text(state: Any) -> str:
    """Return the text of the final message in an agent state mapping."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return ""
    return message_text(messages[-1])


# ---- _block_text ------------------------------------------------------------
def _block_text(block: Any) -> str:
    """Extract text from a single content block."""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        text = block.get("text")
        if isinstance(text, str):
            return text
    return ""

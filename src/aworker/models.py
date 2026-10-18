"""Build LangChain chat models from client-supplied credentials.

When a client injects an external service credential, agents must call that
service with the client's endpoint and key instead of any server-side default.
When no credential is supplied, the configured model id is used as-is.
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from aworker.server.credentials import LLMCredential


# ---- build_chat_model -------------------------------------------------------
def build_chat_model(
    default_model: str,
    credential: LLMCredential | None,
) -> str | BaseChatModel:
    """Return a model id or a chat model bound to the client's credential."""
    if credential is None:
        return default_model

    return init_chat_model(
        credential.model or default_model,
        base_url=credential.base_url,
        api_key=credential.api_key,
    )

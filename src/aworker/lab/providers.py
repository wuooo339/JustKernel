"""One model interface for Deep Agents; credentials never enter the agent workspace."""

import asyncio
import base64
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from aworker.config import Settings


# ---- ModelProfile -----------------------------------------------------------
class ModelProfile(BaseModel):
    name: str
    provider: Literal["openai", "glm", "deepseek", "qwen", "compatible", "chatgpt"]
    model: str
    base_url: str | None = None
    secret: str | None = None
    auth_file: Path | None = None
    effort: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    extra_body: dict = Field(default_factory=dict)
    streaming: bool = True


# ---- ReadOnlyChatGPTLogin ----------------------------------------------------
class ReadOnlyChatGPTLogin:
    """Read the user's existing Codex login without rotating or overwriting its tokens."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()

    # ---- token access -------------------------------------------------------
    def get_token(self):
        from langchain_openai.chatgpt_oauth import _ChatGPTToken

        data = json.loads(self.path.read_text(encoding="utf-8"))
        tokens = data.get("tokens", {})
        access = tokens.get("access_token", "")
        refresh = tokens.get("refresh_token", "")
        if not access or not refresh:
            raise ValueError("ChatGPT login is missing. Sign in locally or configure an API key.")
        try:
            payload = access.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            expires = datetime.fromtimestamp(claims["exp"], UTC)
        except (ValueError, KeyError, IndexError) as exc:
            raise ValueError("ChatGPT login has an unsupported token format") from exc
        if expires.timestamp() <= datetime.now(UTC).timestamp() + 30:
            raise ValueError("ChatGPT login expired; sign in again using the local account tool")
        return _ChatGPTToken(
            access_token=access,
            refresh_token=refresh,
            expires_at=expires,
            account_id=tokens.get("account_id"),
            id_token=tokens.get("id_token"),
        )

    async def aget_token(self):
        return await asyncio.to_thread(self.get_token)

    def get_access_token(self) -> str:
        return self.get_token().access_token

    async def aget_access_token(self) -> str:
        return (await self.aget_token()).access_token


# ---- CompatibleChatOpenAI ---------------------------------------------------
class CompatibleChatOpenAI(ChatOpenAI):
    """Keep the legacy token field expected by OpenAI-compatible providers."""

    # ---- request parameters -------------------------------------------------
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if "max_completion_tokens" in payload:
            payload["max_tokens"] = payload.pop("max_completion_tokens")
        return payload


# ---- QwenThinking ----------------------------------------------------------
class QwenThinking(CompatibleChatOpenAI):
    """Preserve Qwen reasoning in tool history without exposing it as public text."""

    # ---- request history and ordinary/streaming response decoding -----------
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for original, encoded in zip(
            self._convert_input(input_).to_messages(), payload["messages"], strict=True
        ):
            if (
                isinstance(original, AIMessage)
                and "reasoning_content" in original.additional_kwargs
            ):
                encoded["reasoning_content"] = original.additional_kwargs["reasoning_content"]
        return payload

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, raw.get("choices", []), strict=True):
            reasoning = choice.get("message", {}).get("reasoning_content")
            if reasoning is not None:
                generation.message.additional_kwargs["reasoning_content"] = reasoning
        return result

    def _convert_chunk_to_generation_chunk(self, chunk, default_chunk_class, base_generation_info):
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        choices = chunk.get("choices", [])
        if result and choices:
            reasoning = choices[0].get("delta", {}).get("reasoning_content")
            if reasoning is not None:
                result.message.additional_kwargs["reasoning_content"] = reasoning
        return result


# ---- DeepSeekThinking -------------------------------------------------------
class DeepSeekThinking(ChatDeepSeek):
    """Retain provider reasoning for every assistant turn, including non-tool turns."""

    # ---- request history ----------------------------------------------------
    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = self._convert_input(input_).to_messages()
        for original, encoded in zip(messages, payload["messages"], strict=True):
            if isinstance(original, AIMessage):
                reasoning = original.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    encoded["reasoning_content"] = reasoning
        return payload


# ---- ModelRegistry ----------------------------------------------------------
class ModelRegistry:
    def __init__(self, settings: Settings, vault=None):
        self.settings = settings
        self.vault = vault
        self.local_keys = {}
        source = settings.lab_models_file
        if not source.is_file():
            source = Path(__file__).parent / "resources" / "models.toml"
        data = tomllib.loads(source.read_text(encoding="utf-8-sig"))
        local = source.with_name(source.stem + ".local.toml")
        if local.is_file():
            overrides = tomllib.loads(local.read_text(encoding="utf-8-sig"))
            data.setdefault("models", {}).update(overrides.get("models", {}))
        self.profiles = {
            key: ModelProfile.model_validate(value) for key, value in data.get("models", {}).items()
        }
        self.reload_local()

    # ---- metadata and clients ----------------------------------------------
    def reload_local(self):
        if self.vault is None:
            return
        path = self.vault.folder / "models.json"
        if not path.is_file():
            return
        for key, row in json.loads(path.read_text(encoding="utf-8")).items():
            self.profiles[key] = ModelProfile.model_validate(row["profile"])
            if row.get("key"):
                from pydantic import SecretStr

                self.local_keys[key] = SecretStr(
                    self.vault._cipher().decrypt(row["key"].encode()).decode()
                )

    def catalog(self) -> list[dict]:
        result = []
        for key, profile in self.profiles.items():
            configured = bool(
                self.local_keys.get(key)
                or self.settings.lab_provider_keys.get(profile.secret or key)
            )
            detail = "API key required"
            if profile.provider == "chatgpt":
                configured = bool(profile.auth_file and profile.auth_file.expanduser().is_file())
                detail = "ChatGPT plan login; experimental LangChain model adapter"
            result.append(
                {
                    "id": key,
                    "name": profile.name,
                    "provider": profile.provider,
                    "model": profile.model,
                    "effort": profile.effort,
                    "configured": configured,
                    "detail": detail,
                    "harness": "deepagents",
                    "base_url": profile.base_url,
                    "max_tokens": profile.max_tokens,
                    "extra_body": profile.extra_body,
                }
            )
        return result

    def build(self, key: str) -> BaseChatModel:
        if key not in self.profiles:
            raise ValueError("unknown model profile; configure models.toml first")
        profile = self.profiles[key]
        common = {
            "model": profile.model,
            "streaming": profile.streaming,
            "timeout": 120,
            "max_retries": 1,
        }
        if self.settings.lab_proxy_url:
            common.update(
                http_client=httpx.Client(proxy=self.settings.lab_proxy_url),
                http_async_client=httpx.AsyncClient(proxy=self.settings.lab_proxy_url),
            )
        if profile.provider == "chatgpt":
            from langchain_openai.chat_models.codex import _ChatOpenAICodex

            if profile.auth_file is None:
                raise ValueError("configure a local ChatGPT auth_file")
            if profile.effort:
                common["reasoning"] = {"effort": profile.effort}
            return _ChatOpenAICodex(
                **common,
                token_provider=ReadOnlyChatGPTLogin(profile.auth_file),
                originator="justkernel",
                instructions="You are the JustKernel operator engineer.",
                model_kwargs={"parallel_tool_calls": False},
            )
        secret = self.local_keys.get(key) or self.settings.lab_provider_keys.get(
            profile.secret or key
        )
        if secret is None:
            raise ValueError(f"API key for model profile '{key}' is not configured")
        common.update(
            api_key=secret.get_secret_value(),
            base_url=profile.base_url,
        )
        if profile.max_tokens is not None:
            token_parameter = (
                "max_completion_tokens" if profile.provider == "openai" else "max_tokens"
            )
            common[token_parameter] = profile.max_tokens
        if profile.effort:
            common["reasoning_effort"] = profile.effort
        if profile.extra_body:
            common["extra_body"] = profile.extra_body
        if profile.provider == "deepseek":
            # Preserve reasoning_content in tool-call history as required by DeepSeek.
            return DeepSeekThinking(**common)
        if profile.provider == "qwen":
            return QwenThinking(**common, stream_usage=True)
        model_class = ChatOpenAI if profile.provider == "openai" else CompatibleChatOpenAI
        return model_class(**common)

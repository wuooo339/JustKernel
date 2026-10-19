"""Private model configuration edited through the local workbench."""

import json
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator

from aworker.lab.providers import ModelProfile


# ---- APIModelSave -----------------------------------------------------------
class APIModelSave(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    provider: Literal["openai", "glm", "deepseek", "qwen", "compatible"]
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=1000)
    api_key: SecretStr | None = None
    effort: str | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    extra_body: dict = Field(default_factory=dict)

    # ---- endpoint boundary --------------------------------------------------
    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value):
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "use an HTTP(S) base URL without embedded credentials, query or fragment"
            )
        if url.hostname in {"open.bigmodel.cn", "api.z.ai"} and "/coding/" in url.path:
            raise ValueError(
                "GLM Coding Plan is restricted to supported tools; "
                "use the standard API endpoint for this application"
            )
        if url.hostname in {
            "coding.dashscope.aliyuncs.com",
            "token-plan.cn-beijing.maas.aliyuncs.com",
        }:
            raise ValueError(
                "this subscription endpoint is for interactive supported tools; "
                "use the standard Model Studio API"
            )
        return value.rstrip("/")


# ---- save_api_model ---------------------------------------------------------
def save_api_model(service, request: APIModelSave) -> dict:
    service.require_idle()
    current = service.registry.profiles.get(request.id)
    if current and current.provider == "chatgpt":
        raise ValueError(
            "choose a new ID; an existing ChatGPT login profile cannot be replaced here"
        )
    vault = service.servers
    path = vault.folder / "models.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    row = data.get(request.id, {})
    profile = ModelProfile(
        name=request.name,
        provider=request.provider,
        model=request.model,
        base_url=request.base_url,
        secret=request.id,
        effort=request.effort or None,
        max_tokens=request.max_tokens,
        extra_body=request.extra_body,
        streaming=True,
    )
    row["profile"] = profile.model_dump(mode="json")
    if request.api_key and request.api_key.get_secret_value():
        row["key"] = vault._cipher().encrypt(request.api_key.get_secret_value().encode()).decode()
    data[request.id] = row
    vault.folder.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)
    service.registry.reload_local()
    return {"id": request.id, "saved": True, "models": service.registry.catalog()}

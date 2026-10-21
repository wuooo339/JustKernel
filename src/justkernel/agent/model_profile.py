"""Immutable model profile."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from justkernel.agent.errors import ModelProfileError


# ---- ModelProfile -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    provider: str
    model: str
    secret_ref: str
    base_url: str | None = None
    effort: str | None = None
    max_tokens: int | None = None
    extra_body: Mapping[str, object] = field(default_factory=dict)
    streaming: bool = True
    supports_tools: bool = True

    def __post_init__(self) -> None:
        for field_name in ("name", "provider", "model", "secret_ref"):
            if not getattr(self, field_name):
                raise ModelProfileError(f"{field_name} must be non-empty")
        if self.base_url is not None and not self.base_url:
            raise ModelProfileError("base_url must be non-empty")
        if self.effort is not None and not self.effort:
            raise ModelProfileError("effort must be non-empty")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ModelProfileError("max_tokens must be positive")
        object.__setattr__(self, "extra_body", MappingProxyType(dict(self.extra_body)))

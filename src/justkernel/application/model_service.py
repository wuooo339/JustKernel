"""Application service for model profile routing."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.agent.errors import ModelFallbackError, ModelProfileError
from justkernel.agent.model_profile import ModelProfile
from justkernel.agent.model_routing import ModelRouting
from justkernel.application.ports import ModelProfileRegistryPort


# ---- ModelSelection ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ModelSelection:
    profile: ModelProfile
    requested_profile: str
    fallback: bool
    reason: str | None = None


# ---- ModelRoutingService ----------------------------------------------------
class ModelRoutingService:
    def __init__(
        self,
        routing: ModelRouting,
        profiles: ModelProfileRegistryPort,
    ) -> None:
        self.routing = routing
        self.profiles = profiles

    def resolve(
        self,
        role: str,
        direction_id: str | None = None,
        task_profile: str | None = None,
        instance_profile: str | None = None,
    ) -> ModelProfile:
        name = self.routing.resolve(role, direction_id, task_profile, instance_profile)
        return self._profile(name)

    def fallback(self, failed_profile: str, reason: str) -> ModelSelection:
        for name in self.routing.allowed_fallbacks:
            if name == failed_profile:
                continue
            try:
                profile = self._profile(name)
            except ModelProfileError:
                continue
            return ModelSelection(
                profile=profile,
                requested_profile=failed_profile,
                fallback=True,
                reason=reason,
            )
        raise ModelFallbackError("no configured fallback profile is available")

    def provider_limit(self, provider: str) -> int | None:
        for name, limit in self.routing.provider_concurrency:
            if name == provider:
                return limit
        return None

    def _profile(self, name: str) -> ModelProfile:
        try:
            profile = self.profiles.get(name)
        except KeyError as error:
            raise ModelProfileError(f"model profile not found: {name}") from error
        if not profile.supports_tools:
            raise ModelProfileError(f"model profile lacks tool support: {name}")
        return profile

"""Model routing policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from justkernel.shared.digest import Digest
from justkernel.shared.json import digest_json
from justkernel.testing.policy import PolicyError


# ---- _mapping ---------------------------------------------------------------
def _mapping(pairs: tuple[tuple[str, str], ...], name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in pairs:
        if not key or not value:
            raise PolicyError(f"{name} keys and values must be non-empty")
        if key in result:
            raise PolicyError(f"{name} contains duplicate key {key!r}")
        result[key] = value
    return result


# ---- ModelRouting -----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ModelRouting:
    system_default: str
    role_defaults: tuple[tuple[str, str], ...] = ()
    direction_defaults: tuple[tuple[str, str], ...] = ()
    allowed_fallbacks: tuple[str, ...] = ()
    provider_concurrency: tuple[tuple[str, int], ...] = ()
    price_source: str = "configured"

    def __post_init__(self) -> None:
        if not self.system_default:
            raise PolicyError("system_default must be non-empty")
        _mapping(self.role_defaults, "role_defaults")
        _mapping(self.direction_defaults, "direction_defaults")
        if any(not profile for profile in self.allowed_fallbacks):
            raise PolicyError("allowed_fallbacks entries must be non-empty")
        providers: set[str] = set()
        for provider, limit in self.provider_concurrency:
            if not provider or provider in providers:
                raise PolicyError("provider_concurrency providers must be unique and non-empty")
            if limit <= 0:
                raise PolicyError("provider_concurrency limit must be positive")
            providers.add(provider)
        if not self.price_source:
            raise PolicyError("price_source must be non-empty")

    def resolve(
        self,
        role: str,
        direction_id: str | None = None,
        task_profile: str | None = None,
        instance_profile: str | None = None,
    ) -> str:
        if instance_profile:
            return instance_profile
        if task_profile:
            return task_profile
        directions = _mapping(self.direction_defaults, "direction_defaults")
        if direction_id and direction_id in directions:
            return directions[direction_id]
        roles = _mapping(self.role_defaults, "role_defaults")
        if role in roles:
            return roles[role]
        return self.system_default

    def fallback_allowed(self, profile: str) -> bool:
        return profile in self.allowed_fallbacks

    def digest(self) -> Digest:
        return digest_json(asdict(self))

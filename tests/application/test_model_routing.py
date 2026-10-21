from __future__ import annotations

import pytest

from justkernel.agent.errors import ModelFallbackError, ModelProfileError
from justkernel.agent.model_profile import ModelProfile
from justkernel.agent.model_routing import ModelRouting
from justkernel.agent.state import Role
from justkernel.application.fakes import InMemoryModelProfileRegistry
from justkernel.application.model_service import ModelRoutingService


# ---- helpers ----------------------------------------------------------------
def _profile(
    name: str,
    *,
    provider: str = "openai",
    supports_tools: bool = True,
    **overrides: object,
) -> ModelProfile:
    values: dict[str, object] = {
        "name": name,
        "provider": provider,
        "model": f"model-{name}",
        "secret_ref": "secret-1",
        "supports_tools": supports_tools,
    }
    values.update(overrides)
    return ModelProfile(**values)


def _service(*, allowed_fallbacks: tuple[str, ...] = ("fallback",)) -> ModelRoutingService:
    routing = ModelRouting(
        system_default="system",
        role_defaults=(("MENTOR", "role"),),
        direction_defaults=(("dir-1", "direction"),),
        allowed_fallbacks=allowed_fallbacks,
        provider_concurrency=(("openai", 2),),
    )
    registry = InMemoryModelProfileRegistry()
    for profile in (
        _profile("system"),
        _profile("role"),
        _profile("direction"),
        _profile("task"),
        _profile("instance"),
        _profile("fallback"),
    ):
        registry.add(profile)
    return ModelRoutingService(routing, registry)


# ---- profile validation -----------------------------------------------------
def test_model_profile_validation() -> None:
    profile = _profile("system")
    assert profile.name == "system"
    assert profile.supports_tools is True

    for field in ("name", "provider", "model", "secret_ref"):
        values = {
            "name": "system",
            "provider": "openai",
            "model": "model",
            "secret_ref": "secret",
            field: "",
        }
        with pytest.raises(ModelProfileError):
            ModelProfile(**values)

    with pytest.raises(ModelProfileError):
        _profile("system", max_tokens=0)


# ---- routing priority -------------------------------------------------------
def test_routing_priority() -> None:
    service = _service()

    assert service.resolve(Role.MENTOR).name == "role"
    assert service.resolve(Role.MENTOR, direction_id="dir-1").name == "direction"
    assert (
        service.resolve(
            Role.MENTOR,
            direction_id="dir-1",
            task_profile="task",
        ).name
        == "task"
    )
    assert (
        service.resolve(
            Role.MENTOR,
            direction_id="dir-1",
            task_profile="task",
            instance_profile="instance",
        ).name
        == "instance"
    )
    assert service.resolve(Role.TESTER).name == "system"


def test_resolution_requires_existing_tool_capable_profile() -> None:
    service = _service()
    routing = ModelRouting(system_default="missing")
    missing_service = ModelRoutingService(routing, service.profiles)

    with pytest.raises(ModelProfileError):
        missing_service.resolve(Role.TESTER)

    registry = InMemoryModelProfileRegistry()
    registry.add(_profile("system", supports_tools=False))
    no_tools = ModelRoutingService(ModelRouting(system_default="system"), registry)
    with pytest.raises(ModelProfileError):
        no_tools.resolve(Role.TESTER)


# ---- fallback ---------------------------------------------------------------
def test_configured_fallback_is_selected() -> None:
    service = _service(allowed_fallbacks=("missing", "fallback"))

    selection = service.fallback("role", "provider rate limit")

    assert selection.profile.name == "fallback"
    assert selection.requested_profile == "role"
    assert selection.fallback is True
    assert selection.reason == "provider rate limit"


def test_unconfigured_or_unavailable_fallback_is_rejected() -> None:
    with pytest.raises(ModelFallbackError):
        _service(allowed_fallbacks=()).fallback("role", "rate limit")

    with pytest.raises(ModelFallbackError):
        _service(allowed_fallbacks=("missing",)).fallback("role", "rate limit")


# ---- provider limits --------------------------------------------------------
def test_provider_concurrency_lookup() -> None:
    service = _service()

    assert service.provider_limit("openai") == 2
    assert service.provider_limit("unknown") is None

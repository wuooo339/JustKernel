# F04-01 ModelProfile and Provider Routing Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement immutable model profiles and an application routing service with priority resolution, tool-capability checks, configured fallback, and provider concurrency lookup.

**Architecture:** `agent/model_profile.py` defines the profile value object; `application/model_service.py` composes `ModelRouting`, `ModelProfileRegistryPort`, and returns a `ModelSelection`. Fallback is limited to `ModelRouting.allowed_fallbacks`.

**Spec:** `SPEC/05-agent-runtime-and-skills.md` §7; `SPEC/13-generation-and-iteration-contract.md` §9.

## Global Constraints

- Priority: instance > task > direction > role > system default.
- A resolved profile must exist and support tool calling.
- Fallback only uses configured compatible profiles; no unconfigured fallback.
- Provider concurrency is looked up from routing, not hardcoded.
- No real provider calls in this feature.
- Application imports ports/domain only, never platform.
- No old-code imports or old tests.

## Files

- Create: `src/justkernel/agent/model_profile.py` — `ModelProfile`
- Modify: `src/justkernel/agent/errors.py` — `ModelProfileError`, `ModelFallbackError`
- Modify: `src/justkernel/shared/error_codes.py` — model codes
- Modify: `src/justkernel/application/ports.py` — `ModelProfileRegistryPort`
- Modify: `src/justkernel/application/fakes.py` — `InMemoryModelProfileRegistry`
- Create: `src/justkernel/application/model_service.py` — `ModelSelection`, `ModelRoutingService`
- Create: `tests/application/test_model_routing.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class ModelProfile:
    name: str; provider: str; model: str; secret_ref: str
    base_url: str | None; effort: str | None; max_tokens: int | None
    extra_body: Mapping[str, object]; streaming: bool
    supports_tools: bool

class ModelSelection:
    profile: ModelProfile
    requested_profile: str
    fallback: bool
    reason: str | None

class ModelRoutingService:
    def resolve(self, role, direction_id=None, task_profile=None,
                instance_profile=None) -> ModelProfile: ...
    def fallback(self, failed_profile: str, reason: str) -> ModelSelection: ...
    def provider_limit(self, provider: str) -> int | None: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/application/test_model_routing.py`:
- profile validation;
- priority resolution;
- missing profile/tool capability rejection;
- configured fallback and unavailable fallback;
- provider concurrency lookup.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_model_routing.py
```

Expected: import failure for missing profile/service.

- [ ] **Step 3: Implement**

Add the profile, registry port/fake, and routing service. Keep functions ≤40 lines.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_model_routing.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```

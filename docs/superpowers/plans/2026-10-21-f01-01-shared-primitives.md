# F01-01 Shared Primitives Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Provide the pure, I/O-free primitives every domain module uses: identifiers, digests, canonical JSON, clock, principal, project paths, and stable errors.

**Architecture:** All modules live under `src/justkernel/shared/` and depend only on the Python standard library. No database, HTTP, model, or filesystem imports. `shared/__init__.py` re-exports the public names.

**Spec:** `SPEC/04-domain-model.md` §3, `SPEC/13-generation-and-iteration-contract.md` §1.

## Global Constraints

- IDs: UUID4 rendered as 32 lowercase hex characters.
- Digests: SHA-256 rendered as 64 lowercase hex characters.
- Clock: Unix epoch **milliseconds** as `int` (decision D-011).
- Canonical JSON: UTF-8, sorted keys, compact separators, no NaN/Infinity.
- ProjectPath: relative POSIX, no absolute path, `..`, backslash, NUL, empty segments, or drive prefix.
- Principal: `agent:<id>`, `human`, `system`.
- Errors: stable `code` strings; no secrets in messages.
- Domain/shared modules must not import `justkernel.platform`.

## Files

- Create: `src/justkernel/shared/ids.py`
- Create: `src/justkernel/shared/digest.py`
- Create: `src/justkernel/shared/json.py`
- Create: `src/justkernel/shared/clock.py`
- Create: `src/justkernel/shared/principal.py`
- Create: `src/justkernel/shared/paths.py`
- Create: `src/justkernel/shared/errors.py`
- Modify: `src/justkernel/shared/__init__.py`
- Create: `tests/unit/shared/test_ids.py`
- Create: `tests/unit/shared/test_digest.py`
- Create: `tests/unit/shared/test_canonical_json.py`
- Create: `tests/unit/shared/test_clock.py`
- Create: `tests/unit/shared/test_principal.py`
- Create: `tests/unit/shared/test_project_path.py`
- Create: `tests/unit/shared/test_errors.py`
- Modify: `docs/refactor/decision-log.md` (D-011 clock unit)
- Modify: `TODO.md`
- Modify: `docs/refactor/feature-log.md`

## Interfaces

```python
class Identifier:  # dataclass(frozen=True, slots=True)
    value: str
    @classmethod
    def generate(cls) -> Self: ...

class ClusterId(Identifier): ...
class AgentId(Identifier): ...
class DirectionId(Identifier): ...
class TaskId(Identifier): ...
class CandidateId(Identifier): ...
class TestRecordId(Identifier): ...
class MessageId(Identifier): ...
class LeaseId(Identifier): ...

class Digest:  # dataclass(frozen=True, slots=True)
    value: str
    @classmethod
    def from_bytes(cls, data: bytes) -> Self: ...
    @classmethod
    def from_text(cls, text: str) -> Self: ...

def canonical_json(value: object) -> str: ...
def canonical_bytes(value: object) -> bytes: ...
def digest_json(value: object) -> Digest: ...

class Clock(Protocol):
    def now_ms(self) -> int: ...

class SystemClock: ...
class FakeClock: ...  # set/advance

class Principal:  # dataclass(frozen=True, slots=True)
    kind: Literal["agent", "human", "system"]
    agent_id: AgentId | None
    @classmethod
    def agent(cls, agent_id: AgentId) -> Self: ...
    @classmethod
    def human(cls) -> Self: ...
    @classmethod
    def system(cls) -> Self: ...
    @classmethod
    def parse(cls, value: str) -> Self: ...

class ProjectPath:  # dataclass(frozen=True, slots=True)
    value: str

class JustKernelError(Exception):
    code: str
    message: str

class InvalidIdError(JustKernelError): ...
class InvalidDigestError(JustKernelError): ...
class InvalidJsonError(JustKernelError): ...
class InvalidClockError(JustKernelError): ...
class InvalidPrincipalError(JustKernelError): ...
class InvalidProjectPathError(JustKernelError): ...
```

## Steps

- [ ] **Step 1: Write all failing tests**

Create the seven test modules. Cover generation/validation, canonical output, fake clock behavior, principal round-trip, path rejection, and stable error codes.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/unit/shared
```

Expected: collection/import failures because the shared modules do not exist.

- [ ] **Step 3: Implement the primitives**

Implement the interfaces above with standard-library only.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/unit/shared
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Record decision D-011**

Append to `docs/refactor/decision-log.md`: clock unit is Unix epoch milliseconds; why, and cost if wrong.

- [ ] **Step 6: Commit, record, push**

```bash
scripts/push_refactor.sh
```

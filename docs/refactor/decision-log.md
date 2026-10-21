# JustKernel v2 Foundation Decisions

> Scope: P0 decisions that later features depend on. Each decision records why it was made and what it costs if wrong.
> Status: accepted for the independent Refactor workspace.

## D-001 Independent project

**Decision:** `Refactor/` is a standalone `justkernel` implementation based only on `SPEC/`. It does not import, copy, or test the old `../JustKernel` implementation.

**Why:** The new product model is a single-operator role-based cluster, not a continuation of the old multi-team lab. Reusing old behavior/tests would preserve the wrong model.

**Cost if wrong:** Some adapter work (CANN, model providers) must be reimplemented instead of copied; that is accepted.

## D-002 Python, uv, hatchling

**Decision:** Python 3.13+, `uv` for dependency management, hatchling for the wheel/sdist.

**Why:** Matches SPEC 01 §7 and keeps packaging simple. `uv.lock` makes local and CI installs reproducible.

**Cost if wrong:** A later build-backend change touches only `pyproject.toml` and CI.

## D-003 src layout

**Decision:** Production code lives under `src/justkernel/`; tests live under `tests/`.

**Why:** The src layout prevents accidental imports from the working directory and makes editable installs explicit.

**Cost if wrong:** Tooling paths must be updated consistently; no domain code changes.

## D-004 SQLite access

**Decision:** Use the standard-library `sqlite3` with explicit SQL for persistence. No ORM.

**Why:** SPEC 08 relies on partial unique indexes, append-only triggers, explicit transactions, and event/outbox semantics that an ORM would hide.

**Cost if wrong:** More repository boilerplate; migrating to an ORM later would touch adapters, not domain types.

## D-005 IDs and digests

**Decision:** IDs are UUID4 rendered as 32 lowercase hex characters. Digests are SHA-256 rendered as 64 lowercase hex characters.

**Why:** SPEC 04 fixes the ID format; content-addressed artifacts and TestRecord manifests need one spelling across SQLite, JSON, and the web UI.

**Cost if wrong:** A format change requires rewriting stored IDs/artifact paths.

## D-006 Canonical JSON

**Decision:** Persisted structured payloads use UTF-8 JSON with sorted keys and compact separators. NaN/Infinity are rejected in persisted payloads.

**Why:** Idempotency keys, digests, event payloads, and BestSelection records must be reproducible.

**Cost if wrong:** Digest mismatches or non-reproducible records; fixing requires a schema version and re-hashing.

## D-007 Configuration boundary

**Decision:** Only `justkernel.platform.config` may read environment variables. Precedence is CLI > environment > `.env` > defaults. Constructors do not create directories; bootstrap performs explicit setup.

**Why:** SPEC 03 forbids import-time side effects and scattered environment reads. One boundary keeps tests deterministic.

**Cost if wrong:** A hidden environment read would make tests order-dependent; the fix is centralization.

## D-008 Test layers and TDD

**Decision:** Tests are split into `unit`, `application`, `adapters`, `integration`, `architecture`, `web`, and `e2e`. Every behavior feature starts with a failing test; fakes are deterministic (FakeClock/FakeIds, no sleeps).

**Why:** SPEC 11 requires deterministic tests without real models/devices for domain/application layers, plus architecture gates.

**Cost if wrong:** A missing layer boundary shows up as a slow or flaky test; the fix is at the test boundary, not in production code.

## D-009 Feature workflow and push

**Decision:** Each feature follows: plan → RED → GREEN → REFACTOR → target tests → full pytest → mypy → ruff → commit → `scripts/push_refactor.sh` → feature log. One feature is `in_progress` at a time.

**Why:** The TODO is a feature roadmap; small verified increments keep the remote `refactor` branch reviewable.

**Cost if wrong:** Overhead per feature; the workflow can be relaxed only by an explicit human decision.

## D-010 No legacy compatibility

**Decision:** The new project does not preserve old CLI names, old tests, old environment variables, or old behavior as compatibility requirements. SPEC is the only authority.

**Why:** The new product model is a replacement, not a migration of the old implementation. Old code remains in its own worktree for reference only.

**Cost if wrong:** A genuinely needed old adapter must be reimplemented behind a new port and tested in the new project.

## D-011 Clock unit

**Decision:** `Clock.now_ms()` returns Unix epoch **milliseconds** as an `int`. `FakeClock` is the deterministic test implementation; persisted `created_at`/`expires_at` values use the same unit.

**Why:** SPEC stores timestamps as integers. Milliseconds give deterministic ordering and lease TTL precision without floating-point timestamps.

**Cost if wrong:** A future integration that speaks seconds must convert at its boundary; changing stored semantics would require a migration.

## D-012 Execution contracts

**Decision:** Startup/task contracts are immutable dataclasses with canonical-JSON digests. Validation failures raise stable domain errors (`operator_spec.incomplete`, `invalid_task_context`, `invalid_policy`), not generic exceptions.

**Why:** OperatorSpec, TaskContext, and policies are compared and persisted by digest; immutable validated objects keep evidence reproducible and make invalid startup input fail before any agent runs.

**Cost if wrong:** Adding a field changes the digest and requires a new contract version/cluster; that is the intended safety property.

## D-013 Cluster and Direction aggregates

**Decision:** Cluster and Direction are mutable aggregates with explicit command methods and transition guards. Terminal states are irreversible, terminal fields are validated in `__post_init__`, and `max_agents` has a minimum of 6.

**Why:** The SPEC state machines are small but safety-critical; guards keep invalid transitions out of persistence and make event/command tests deterministic.

**Cost if wrong:** A later aggregate split or field addition must update the guard methods and rehydration validation.

## D-014 Agent lifecycle

**Decision:** `AgentInstance` is a mutable aggregate with explicit lifecycle commands. Worker roles require exactly one mentor; non-worker roles reject a mentor. `CLOSED` is terminal and requires `closed_at`. Interrupted agents resume only with a new session id.

**Why:** The role/mentor boundary is a hard ACL prerequisite; encoding it in the aggregate prevents invalid worker creation before repositories or tools see it.

**Cost if wrong:** A future role needs an explicit worker/non-worker classification and transition table update.

## D-015 Task lifecycle and kind constraints

**Decision:** `Task` enforces kind-specific candidate/skill rules in the aggregate: GENERATE has neither, OPTIMIZE has a candidate only, TEST/PROFILE have both. Terminal states require `finished_at`; SUCCEEDED requires `result_ref`; FAILED/CANCELLED/INTERRUPTED require a reason. Retry always uses a new TaskId.

**Why:** These constraints prevent malformed tasks from reaching workers/tools and keep terminal evidence distinguishable from a running task.

**Cost if wrong:** A future task kind must extend the kind table and its terminal-result contract.

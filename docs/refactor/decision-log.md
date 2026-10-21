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

## D-016 Candidate immutability and best selection

**Decision:** `CandidateVersion` is frozen; `SourceRevision` normalizes files and computes a canonical digest. `CandidateGraph` requires parents to exist in the same cluster. `BestSelection` is a separate frozen state machine; only `VALIDATED` may update `cluster.best_candidate_id` (application layer).

**Why:** Candidate source is evidence, not mutable workspace state. Keeping best selection independent prevents a passing test from silently changing the candidate entity or an unvalidated nomination from becoming best.

**Cost if wrong:** Re-importing or re-submitting the same source must use a new CandidateId; best validation needs final task/record IDs.

## D-017 TestRecord, lease, and report boundaries

**Decision:** TestRecord is immutable and rejects contradictory executed/audit fields. HardwareLease is a mutable QUEUED→LEASED→RELEASED/EXPIRED machine with timestamp consistency. ExplorationReport is frozen, revisioned, and requires best (when present) to be one of its candidates.

**Why:** TestRecord is evidence, not scratch state; audit records must never look like executed PASS. Lease transitions are safety-critical, and report references must stay internally consistent.

**Cost if wrong:** Re-testing creates a new record; a lease recovery path must use a new lease or an explicit expired-state transition.

## D-018 ACL and message routing

**Decision:** ACL is a pure role/principal/channel function. Worker tool sets exclude all board tools structurally. The message envelope fixes each `MessageType` to one channel kind and rejects board recipients or worker messages without a recipient.

**Why:** Prompt-level restrictions are not an ACL boundary. Centralizing access and message/channel consistency keeps worker isolation testable and prevents routing mistakes before persistence.

**Cost if wrong:** A new channel/message type must be added to both the channel table and ACL matrix, with a test for each role.

## D-019 Stable codes, events, and invariants

**Decision:** All error classes use the `ErrorCode` registry. Domain events use one immutable envelope with typed event names. Cross-aggregate invariants are pure validators in `cluster/invariants.py`; MessageId deduplication is a stateful inbox.

**Why:** Stable codes make API/error handling testable; one event envelope keeps replay/serialization consistent; pure validators can be reused by application services before persistence.

**Cost if wrong:** Adding a code/event/invariant requires updating the registry and its table-driven test.

## D-020 SQLite journal schema

**Decision:** The cluster journal uses standard-library `sqlite3` with explicit, idempotent DDL and ordered versioned migrations. Partial unique indexes enforce supervisor/direction/task/record/wake constraints; append-only triggers reject event updates/deletes.

**Why:** The schema is part of the evidence and recovery contract. Explicit SQL keeps partial indexes and triggers visible and testable without an ORM.

**Cost if wrong:** Schema changes require a new migration version; existing journals must be migrated forward, never edited in place.

## D-021 UnitOfWork and optimistic concurrency

**Decision:** Use cases run inside a `UnitOfWork` backed by one SQLite transaction. Cluster/Agent updates require an expected version and bump it; stale writes raise `ConcurrencyError`. Events and outbox entries participate in the same transaction. Outbox idempotency keys use `INSERT OR IGNORE`.

**Why:** Aggregate writes, audit events, and delivery records must fail or commit together. Optimistic versions prevent lost updates without long-lived locks.

**Cost if wrong:** A caller must track the expected version; a stale update must reload and retry, never overwrite silently.

## D-022 Artifact store

**Decision:** Artifacts are stored under `sha256/<ab>/<cd>/<digest>` with atomic temp-file writes, file fsync, `os.replace`, POSIX 0600/0700 permissions, and read-time hash verification. Database rows store only digests/relative refs, never absolute paths.

**Why:** Candidates, TestRecord zips, diffs, and profiles are immutable evidence. Content addressing gives dedupe and lets repositories verify integrity independently of a path.

**Cost if wrong:** Large artifacts are still copied once per digest; deletion requires a reference/GC policy rather than direct file removal.

## D-023 Projections and replay

**Decision:** Read models are rebuilt from committed events with a per-projection cursor in the `projections` table. Live `apply_pending` and full `rebuild` use the same view code; rebuilding does not append events or trigger external effects.

**Why:** The board, cluster graph, candidate graph, and queue must be reproducible and consistent between live mode and replay. Cursor isolation lets each view advance independently.

**Cost if wrong:** A projection schema change requires resetting its cursor and rebuilding; view state is not treated as authoritative evidence.

## D-024 Global operator registry

**Decision:** `registry.db` uses `cluster_registry` with a partial unique index on active `operator_id`. Reservation uses a unique `reservation_key`; retry with the same key is idempotent. Terminal release (`COMPLETED/STOPPED/FAILED`) is idempotent and frees the operator for a new cluster.

**Why:** Operator uniqueness must be global, not per-cluster SQLite. A partial unique index gives atomic arbitration across connections/processes without an application lock.

**Cost if wrong:** Terminal release must be driven by the journal terminal commit; a stuck active row blocks new clusters until recovery releases it.

## D-025 Global hardware ledger and fencing

**Decision:** `hardware.db` owns device leases, queue entries, and quarantine. A partial unique index allows one active lease per device; fencing tokens are monotonic per device and checked on execution/release. TTL expiry marks the lease EXPIRED but keeps `execution_active` until `confirm_stopped` clears it.

**Why:** Device arbitration must be global and safe across clusters/processes. Fencing prevents an old/stale executor from starting or overwriting a newer execution.

**Cost if wrong:** A device can remain blocked after a crash until the service confirms the old process stopped; that is intentional over unsafe reassignment.

## D-026 Startup recovery matrix

**Decision:** Startup recovery interrupts RUNNING agents/tasks, pauses RUNNING/CONVERGING clusters while preserving phase, reports pending outbox rows, and reconciles journal leases with the global hardware ledger. Missing/unknown global leases quarantine the device; recovery never reruns a turn/task/test and is idempotent.

**Why:** A crash must leave an auditable paused state, not an automatic replay. Device safety wins over availability when the old execution cannot be confirmed stopped.

**Cost if wrong:** Operators must explicitly resume/re-dispatch after reviewing the recovery report; a device may remain quarantined until cleared.

## D-027 Application ports and deterministic fakes

**Decision:** Application services depend on structural `Protocol` ports in `application/ports.py`, never on platform adapters. Deterministic in-memory fakes live in `application/fakes.py`; fakes use `FakeIds`/explicit time and never perform I/O.

**Why:** Use cases can be tested without SQLite, models, devices, or HTTP, and adapter replacements stay behind ports.

**Cost if wrong:** A port signature change updates its fake and adapter together; fakes are not evidence of real device behavior.

## D-028 Cluster lifecycle service

**Decision:** `ClusterService` is a thin application orchestrator: load via `ClusterRepositoryPort`, call the Cluster aggregate command, then update with the repository's current version. It depends only on ports/domain.

**Why:** Lifecycle rules stay in the aggregate; the service owns persistence/version coordination without duplicating transition logic.

**Cost if wrong:** Concurrent callers can conflict on version and must reload; the service never silently overwrites.

## D-029 Worker lifecycle and task dispatch

**Decision:** `AgentService` creates non-worker agents, opens/closes mentor-owned workers, dispatches tasks through `validate_task_assignment`, and completes tasks by mutating both Task and Worker. Max-agent and supervisor uniqueness checks are application-level; optimistic versions are used for updates.

**Why:** Worker ownership, role/kind matching, and one-running-task rules span aggregates; the application service is the first layer that can enforce them before persistence.

**Cost if wrong:** A worker/task change must update the aggregate, invariant, and service together; the service never silently reassigns ownership.

## D-030 Candidate import and commit

**Decision:** `CandidateService` imports root candidates with system provenance and commits candidates only from RUNNING GENERATE/OPTIMIZE tasks whose worker is an OPTIMIZER. GENERATE has no parent; OPTIMIZE requires an existing same-cluster base candidate.

**Why:** Candidate provenance is evidence. Enforcing it at the application boundary prevents a test task or non-optimizer from creating a candidate and keeps the version DAG valid.

**Cost if wrong:** A task/candidate flow must pass through this service; a new provenance source requires a new use case and test.

## D-031 ToolJob idempotency and record sealing

**Decision:** A ToolJob is keyed by task and request digest; the same request returns the existing job, a conflicting request raises. TestRecord sealing requires the matching TEST/PROFILE task and job, appends one immutable record, and marks the job SUCCEEDED. Audit records have no task/job and are `executed=false`.

**Why:** Duplicate submissions and duplicate terminal records would corrupt evidence. Request digests distinguish an idempotent retry from a conflicting request.

**Cost if wrong:** A parameter change requires a new Task/Job; old jobs/records remain immutable for audit.

## D-032 Best selection, reports, and budget

**Decision:** Best nomination requires full-PASS evidence for the candidate; final validation requires full-PASS final records and updates the BestSelection only. Reports must reference existing same-cluster candidates/records. Budget uses an idempotent reserve/settle ledger with available-balance checks.

**Why:** Best/report evidence must be reproducible and traceable, while budget reservations prevent overcommitment before calls. Domain errors are converted at the service boundary.

**Cost if wrong:** A failed/incomplete record cannot be used to nominate or validate; budgets must be settled with the same idempotency key.

## D-033 Model profiles and routing

**Decision:** Model profiles are immutable; routing priority is instance > task > direction > role > system. A resolved profile must exist and support tool calling. Fallback only iterates configured `allowed_fallbacks`; provider concurrency comes from routing, not hardcoded.

**Why:** Model choice must be reproducible/auditable and cannot silently change an Agent's ACL or tool capability. Restricting fallback prevents unconfigured models from joining a run.

**Cost if wrong:** A new fallback must be configured in routing and registered as a profile; a missing/incapable profile fails closed.

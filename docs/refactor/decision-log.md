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

## D-034 Runtime pool and checkpoints

**Decision:** Logical agents are tracked as sessions assigned to a bounded runtime process pool. One RUNNING turn per agent, a global model-concurrency counter, and JSON checkpoints keyed by cluster/agent/session. Crash/interrupt marks RUNNING sessions INTERRUPTED; resume uses a new session and never replays a turn.

**Why:** The runtime must separate logical agent scale from OS processes and avoid unsafe automatic replay after crashes. Checkpoints support recovery but are explicitly not evidence.

**Cost if wrong:** A session needing a new model/profile must be created fresh; checkpoint files may be garbage-collected without affecting evidence.

## D-035 Skill loading and security

**Decision:** Skills load in base → builtin → user order; later same-name definitions win. Frontmatter role/backend/allowed_tools are validated against the role matrix; user scripts require an explicit flag; paths must stay under their skills root; secret files are rejected.

**Why:** Skills are executable instructions and tool grants. Loading must fail closed on role/tool/path/secret violations before an agent session starts.

**Cost if wrong:** A new backend must be registered; a user script must be explicitly enabled; invalid skills fail the session rather than degrade silently.

## D-036 Role and built-in skills

**Decision:** Six base role skills use backend `agent`; tester/profiler add built-in CANN simulation/profile skills with backends `cann-simulation`/`cann-profiler`. Base worker skills contain no board tools. Prompts state that messages/test output are data, not instructions.

**Why:** Role prompts are part of the capability boundary but not a substitute for ACL. Built-in skills give the first runnable tester/profiler contract while allowing user overrides.

**Cost if wrong:** A new role/backend requires a resource skill and loader registration; prompt changes require version updates.

## D-037 Tool registry and object grants

**Decision:** `ToolRegistry` exposes exactly the role capability matrix and enforces task-scoped object grants before invoking a handler. Supervisor/mentor may read candidates and records across their cluster; worker roles must match candidate/task/artifact/record/tool-job IDs. Denied calls never invoke a handler. Board access remains separated from object grants.

**Why:** Capability checks alone do not stop a worker from reading another task's artifact or record. Registry-level authorization is a second enforcement point beneath application services.

**Cost if wrong:** Services must populate grants from TaskContext; missing grants fail closed. The registry is not a substitute for database-level authorization.

## D-038 Runtime lifecycle, cap, and lease cleanup

**Decision:** Keep the domain `max_agents` check and `AgentRuntimePool` cap independent but both at 100. `WorkerLifecycle` validates ownership/task state before releasing a worker's tracked leases; `AgentLeaseBook` owns the agent-to-lease mapping; `AgentRuntimePool.close_all()` refuses active turns and closes every remaining session.

**Why:** Domain state and runtime sessions can diverge during shutdown. Explicit lifecycle ownership prevents a closed worker from leaving a leased device or an open session behind.

**Cost if wrong:** Callers must use `WorkerLifecycle` instead of `AgentService.close_worker` when leases exist. A crash between lease release and domain close still needs recovery by lease/job inspection.

## D-039 ToolJob state machine

**Decision:** ToolJob owns its immutable state transitions (`start`, `timeout`, `cancel`, `interrupt`, `fail`, `succeed`). Queue timeout is anchored at submission time; execution timeout starts when the job becomes RUNNING. Sealing a TestRecord requires RUNNING. Reads are limited to the Task's own worker and return a `ToolJobView`.

**Why:** Submit must return immediately while the job is queued, and timeout/terminal behavior must be testable without a live backend. Centralizing transitions prevents services from overwriting terminal jobs.

**Cost if wrong:** Queue position is currently a single-job placeholder until the hardware queue adapter exists. A timed-out job does not yet release device resources; that belongs to F05-02.

## D-040 Hardware queue adapter

**Decision:** `HardwareQueue` selects queued rows by priority/FIFO and acquires the ledger lease before marking the row LEASED. Release marks DONE; expiry marks EXPIRED and quarantines only when execution was active; `confirm_stopped` clears the lease's execution flag and quarantine. Queue ordering and lease exclusivity remain SQLite-backed.

**Why:** The ledger enforces one lease per device, but without a queue claim path, queued jobs could never be dispatched or safely recovered.

**Cost if wrong:** A crash between lease acquisition and queue-row update can leave a LEASED row; recovery must reconcile by job/lease. Queue state is not yet wired into ToolJob completion (F05-06).

## D-041 TestRecord zip contract

**Decision:** Build deterministic TestRecord zips with a generated manifest, README, and checksums. `manifest.files` excludes manifest/checksums; `checksums.sha256` covers every other entry. Validation requires the full file set, at least one candidate source, safe paths, matching hashes, JSON semantics, and audit/executed consistency (`results.executed` must match). Audit records must use CANCELLED/UNKNOWN, NONE coverage, null task/job, and an audit id.

**Why:** A TestRecord is only evidence if its archive is complete and tamper-evident. Separating format/readers, builder, and validator keeps each domain module under 300 lines.

**Cost if wrong:** Payloads are still supplied by the backend/service; F05-06 must ensure real source/log/results replace placeholders. Profile/trace external references are not yet represented.

## D-042 CANN simulation backend

**Decision:** `CannSimulationBackend` implements `ToolBackendPort` with immutable request capture, deterministic job IDs/execution caching, and explicit `CannEnvironment` values. `FakeCannRunner` produces PASS/FAIL/ERROR evidence without subprocesses or devices. Environment fingerprints are canonical JSON digests including the selected device.

**Why:** The first tester/profiler flow needs a realistic, testable backend contract without requiring CANN hardware. Unknown toolchain values are rejected rather than inferred.

**Cost if wrong:** The fake runner is not a compiler/device; real CANN command execution and artifact packaging remain future adapter work. The backend does not yet persist results or release leases.

## D-043 TaskContext authorization

**Decision:** `TaskContextService` creates immutable context snapshots only for the task's mentor, requires non-GENERATE base refs to match the task candidate/source digest/cluster, rejects already-expired grants, and authorizes artifact reads against task worker/mentor, digest, read-only scope prefix, and expiry. Artifact bytes are returned only after authorization.

**Why:** Context and feedback are the optimizer's entire input boundary; enforcing binding and grant checks prevents a task from reading another task's private artifacts.

**Cost if wrong:** Contexts are not yet persisted by a repository, and feedback record/skill/environment digests are not cross-validated here. F05-06 must persist the context ref/digest and package real evidence.

## D-044 Evidence chain and archive gate

**Decision:** `EvidenceChainService` allocates the record id before building the archive, validates/stores the archive, then seals the same record id. `EvidenceGate` revalidates the stored archive and compares manifest fields against the record before best nomination. A fabricated PASS with no matching archive is rejected. Existing callers without a gate keep their behavior.

**Why:** A record object alone is not evidence. The gate closes the gap between a PASS-typed record and a real, executed, checksummed archive.

**Cost if wrong:** Payload construction remains the caller's responsibility; the chain does not yet synthesize task/context/skill payloads from services. A crash after artifact store success but before record seal can leave an unreferenced artifact.

## D-045 Validated cluster startup

**Decision:** `ClusterStartService` validates the full startup request before reserving the operator: start-mode source rules, tester/profiler skills, backend allow-list, role counts, capacity, and timestamps. It preallocates the cluster id, reserves the global registry, creates the supervisor/initial roles, then transitions to RUNNING. Failures close created agents, fail an initializing cluster, and release the reservation.

**Why:** Startup spans several aggregates and a global reservation; validating first avoids orphaned reservations, while role creation must not exceed `max_agents`.

**Cost if wrong:** Initial role skills are currently empty; role skill loading and IMPORT baseline candidate creation remain F06-02+ work. A process crash between reservation and cleanup still requires recovery.

## D-046 Bootstrap modes

**Decision:** `BootstrapService` requires a RUNNING/BOOTSTRAPPING started cluster in the matching mode and an initial mentor. GENERATE inserts an ACTIVE baseline direction only; IMPORT inserts the same direction plus a system-authored root candidate bound to that direction. Neither path sets `baseline_candidate_id` or marks the candidate PASS.

**Why:** The baseline direction and imported root are setup inputs, not evidence. Keeping candidate creation in the same bootstrap path ensures the root candidate has valid provenance and a direction before testing.

**Cost if wrong:** Direction persistence is in-memory until the P7 repository adapter. Re-bootstrap idempotency and baseline establishment remain F06-03.

## D-047 Baseline establishment and bootstrap attempts

**Decision:** `BaselineService` counts each completed bootstrap validation attempt per cluster. A full executed TEST PASS establishes the baseline and moves phase to OPTIMIZING; a failed attempt exhausts `max_bootstrap_attempts` and stops the cluster with `baseline_not_established`. Success at the limit still establishes. Candidate/evidence must belong to the cluster/candidate and be TEST kind.

**Why:** Baseline creation is the transition from generation/import to optimization; it must be evidence-gated and bounded by an explicit bootstrap budget.

**Cost if wrong:** Attempt counts are in-memory per service. Policy-digest/environment binding and failure report generation remain later convergence/report work.

## D-048 Feedback handoff

**Decision:** `FeedbackHandoffService` validates mentor/task/candidate/record ownership before changes, fails a matching running old task via `AgentService.fail_task`, closes the old optimizer, builds a new TaskContext with failed-record feedback and candidate history, opens a replacement optimizer, and assigns a new OPTIMIZE task with `retry_of_task_id` and a fixed context digest. A running old task is preserved as terminal FAILED; record IDs/evidence are never overwritten.

**Why:** A replacement worker must not rely on the old session; the failure evidence and prior attempt must be explicit and immutable in the new task.

**Cost if wrong:** Resource grants are caller-supplied and must already target the new task. Context persistence and worker-Lease cleanup are separate P7/P6 concerns.

## D-049 Wake scheduler

**Decision:** `WakeScheduler` deduplicates `(agent_id,event_id)`, merges pending events with `wake_debounce_ms`, allows one CLAIMED turn per agent, keeps notifications pending while RUNNING, and schedules a one-shot deadline wake from an explicit WAIT. Stale expected agent versions cannot be claimed.

**Why:** Wake scheduling must be deterministic and avoid duplicate model turns or races when multiple events arrive during a running Turn.

**Cost if wrong:** Scheduler state is in-memory and does not yet share the transaction/outbox with event append. Event ordering uses arrival order rather than the persisted event sequence, and watchdog behavior is F06-06.

## D-050 Watchdog stall detection

**Decision:** `WatchdogService` consumes an explicit activity snapshot (active tasks, turns, pending wakes, valid WAITs). A RUNNING cluster with none of these emits one supervisor-wake action; a repeated check beyond `max_stalled_wakes` pauses it. Activity or a non-RUNNING state resets the counter.

**Why:** Watchdog decisions must separate idle from legitimate WAIT and avoid repeatedly waking a supervisor when nothing has changed.

**Cost if wrong:** Activity is currently supplied by the caller rather than computed from repositories/runtime. The result carries a `CLUSTER_STALLED` action/event type but does not yet append an outbox event.

## D-051 Budget, plateau and duplicate candidates

**Decision:** `BudgetService` isolates `final_validation_reserve` from exploration availability, delegates actual reservations/settlements to the ledger, and tracks comparable rounds, plateau streaks, consecutive failures and caps in memory. Only comparable rounds count; improvement resets plateau/failures. `CandidateService.find_duplicate()` returns the earliest same-source candidate without deleting either candidate.

**Why:** Final validation must not be starved by exploration, and plateau decisions must not treat tool failures as performance plateaus. Duplicate candidates retain provenance while allowing the mentor/supervisor to avoid automatic re-experimentation.

**Cost if wrong:** Round/failure counters and duplicate decisions are not persisted; the caller must honor `can_explore`/duplicate results. Budget ledger atomicity between reserve calls remains the adapter's responsibility.

## D-052 Convergence and completion

**Decision:** `ConvergenceService` validates the pending best selection with final full-PASS evidence before any cluster mutation, writes the exploration report, then converges the cluster, applies the best candidate and report, and completes it. A failed final validation leaves cluster state, best, report and selection pending. `ClusterService` exposes explicit set-best/attach-report/complete commands.

**Why:** COMPLETED must only be reachable through validated evidence plus a linked report; a failed final check must not overwrite the last valid best.

**Cost if wrong:** Performance-target profile gating is not yet enforced here. A report write failure after selection validation can leave a VALIDATED selection without cluster completion.

## D-053 Resume and late results

**Decision:** `ResumeService.resume()` only transitions a PAUSED cluster to RUNNING and never starts or replays tasks/jobs. A late result requires an INTERRUPTED TEST/PROFILE task and matching INTERRUPTED job, appends a `late_completion` TestRecord with the original task/job ids, and leaves both terminal states unchanged. Late records are excluded from `is_full_pass`.

**Why:** Recovery must preserve audit history without silently converting late execution into baseline/best evidence or rerunning old side effects.

**Cost if wrong:** Resume does not yet verify device leases/artifacts or wake the supervisor. Task/job interruption must come from the recovery path; late archives are limited to one record per task.

## D-054 Fake closed-loop acceptance

**Decision:** The fake e2e suite drives the real application services through generate/bootstrap, baseline, optimization, testing, best nomination, convergence/report, failed-candidate handoff, profile gating, duplicate wake/candidate handling, watchdog WAIT, pause/resume, registry/device exclusivity and bootstrap-budget failure. `BestSelectionService` gains an optional `profile_required` gate for performance-target nominations.

**Why:** P6 needs an integration proof that the independent services compose without real models/devices while preserving evidence and terminal-state guarantees.

**Cost if wrong:** The loop uses in-memory repositories and a deterministic fake tool backend; profile threshold/regression comparison and HTTP/UI wiring remain future work.

## D-055 HTTP API skeleton

**Decision:** Add a FastAPI adapter under `platform/http`: immutable DTOs, RFC7807 `application/problem+json` errors with stable code/status mapping, an in-memory idempotency store/middleware, and a minimal `/api/v1/system/health` app factory. Successful POST responses are cached by `Idempotency-Key`; reusing a key with a different body returns 409.

**Why:** P7 routes need one contract for read models, errors and retries before any feature endpoints are added. Keeping the adapter outside domain/application preserves dependency boundaries.

**Cost if wrong:** The idempotency store is process-local and unbounded; production persistence/eviction is pending. The app currently exposes only health, with cluster/agent routes in F07-02.

## D-056 HTTP read and lifecycle routes

**Decision:** Add route groups for cluster read/actions/create, agents/directions, tasks/tool-jobs, candidates/records/download, report/board/messages/hardware. `ApiContext` injects repos/services; `X-Agent-Id` enforces task-context/tool-job object ACL. `POST /clusters` maps a validated HTTP body into `StartClusterRequest`; all cluster actions use the existing idempotency middleware.

**Why:** The UI/API needs DTO-only reads and auditable commands before SSE/A2A can be layered on. Keeping route groups separate respects file-size gates.

**Cost if wrong:** Task cancellation, agent close, human message posting and full event pagination remain for later features. Task context returns its authorized snapshot metadata, not the full resource because contexts are not yet persisted; hardware device inventory is empty until a device config adapter exists.

## D-057 SSE replay

**Decision:** Expose event pagination and a finite SSE replay stream over `EventStore`. SSE cursor comes from `Last-Event-ID` when present, otherwise `after`; only `seq > cursor` events are emitted, capped at 200. Data is the DTO envelope, never DB columns.

**Why:** The UI and clients need deterministic replay of the append-only event log before live followers/heartbeats are added.

**Cost if wrong:** The stream currently ends after the replay batch and does not yet tail live events or emit 20s keepalives. SQLite connections must be configured thread-safe for the shared API adapter.

## D-058 A2A cluster gateway

**Decision:** Expose one A2A agent card per cluster with only `cluster-status` and `cluster-message`. Status returns cluster summary; messages require topic/message/delivery_id, are published to a dedicated external channel with a human principal, and are idempotent by delivery_id. Worker/board channel targets are rejected.

**Why:** External clients need read/limited-write access without an agent identity or private worker-channel access.

**Cost if wrong:** Delivery IDs are process-local; no authentication/trusted-network gate is implemented yet. External messages are archived on the external channel but not automatically converted into board posts.

## D-059 Redaction, export and download ACL

**Decision:** Add a centralized `Redactor` for registered secrets (≥8 chars) and private roots. Apply it recursively to export payloads and source/report text. Exports/report/source require explicit `X-Human`; record downloads allow human or the owning task worker/mentor. Binary zip downloads are ACL-protected but not rewritten.

**Why:** Human-facing exports and text downloads must not leak registered credentials or private absolute paths, while worker artifacts still require object ownership.

**Cost if wrong:** Human status is header-based until authentication exists. Zip content may contain secrets because binary archives are not redacted; later artifact sanitization is required for untrusted skill output.

## D-060 Web reducer and selectors

**Decision:** Add dependency-free ES modules with a pure event reducer, contiguous-sequence buffering, idempotent replay and read-model selectors. Unknown events advance the cursor without mutating entities. Live dispatch and sorted replay share the reducer. Node's built-in test runner and CI execute the frontend state tests.

**Why:** Live SSE and replay/demo must produce identical UI state; buffering missing sequences prevents out-of-order events from corrupting entity state.

**Cost if wrong:** The reducer covers the current event vocabulary; new event types require explicit projections. Selectors are read-only and do not yet include hardware/agent detail views.

## D-061 Web views and accessibility

**Decision:** Implement framework-free HTML-string views with centralized escaping, accessible section/table/list structure, explicit PENDING vs VALIDATED best markers, visible failed candidates, and `—` for unknown metrics. Tests are DOM-free Node assertions.

**Why:** Views must be testable without a browser toolchain while preserving evidence semantics and safe rendering.

**Cost if wrong:** HTML strings are not yet mounted into a browser shell; CSP and live DOM updates remain F07-08/frontend-shell work.

## D-062 Demo replay fixture

**Decision:** Ship a synthetic JSON event fixture with a JS wrapper that replays through the production web reducer. Node tests validate state/views; Python e2e validates fixture metadata/order and invokes the JS replay. CI installs Node before pytest.

**Why:** UI/demo and replay must be demonstrable without models or devices while exercising the same reducer used by live data.

**Cost if wrong:** The fixture is static and must be updated when event vocabulary or DTO fields change. It is not a backend demo API.

## D-063 Legacy read-only import

**Decision:** Add migration 2 with `legacy_imports`/`legacy_records`, guarded by update/delete triggers. `LegacyImporter` opens the old SQLite file read-only (`mode=ro`, `query_only`), maps legacy teams/members/runs/experiences/events into separate LEGACY rows, and uses the source SHA-256 for idempotency. It creates no active clusters, candidates or board posts.

**Why:** Legacy evidence must remain viewable without contaminating a new cluster's active state or best selection.

**Cost if wrong:** Imported payloads are stored as JSON and are not yet exposed through a dedicated legacy API/UI. Old schemas beyond the synthetic table set require explicit mapping.

## D-064 CLI modes and configuration

**Decision:** `platform/config.py` alone reads `.env`/environment and produces immutable `AppConfig`/`LimitsConfig` objects. CLI overrides are applied via `replace`; `bootstrap/cli.py` supports cluster/demo/worker/migrate, with migrate explicitly requiring `--legacy-db` and running the read-only importer. No `AWORKER_*` compatibility branch exists.

**Why:** Mode and path selection must be deterministic and testable before runtime/server wiring, while migration remains an explicit human action.

**Cost if wrong:** cluster/demo/worker currently print the resolved configuration rather than launching the HTTP server/runtime. Directory permissions and single-service locking are F08-03.

## D-065 Data root and service lock

**Decision:** `initialize_data_root()` explicitly creates the registry/hardware databases, clusters/private directories and service lock with 0700 directories/0600 files, tightening existing modes. `ServiceLock` uses POSIX `flock` or Windows `msvcrt` and is exclusive per data root. CLI migrate initializes the layout and holds the lock during import.

**Why:** Local state, secrets and singleton control-plane ownership need one deterministic, permission-safe initialization path.

**Cost if wrong:** The lock is filesystem-local and advisory; cluster/demo/worker do not acquire it until server startup wiring. Network filesystems may not provide reliable `flock`.

## D-066 Legacy-reference guard

**Decision:** Extend the architecture gate to scan source/tests, `pyproject.toml`, CLI/config runtime code and the legacy importer for legacy package names and environment prefixes. The test constructs the forbidden tokens dynamically so it does not match itself. Documentation that explains independence is excluded.

**Why:** Deleting old modules is insufficient if a package entrypoint or runtime compatibility branch can reintroduce the old namespace.

**Cost if wrong:** The guard is textual; dynamically constructed names or generated artifacts are covered only by packaging checks in F08-05.

## D-067 Packaging and supply-chain gate

**Decision:** Whitelist sdist contents and exclude local agent/index state; add `scripts/check_dist.py` to assert wheel/sdist layout, required resources, only `fastapi`/`pyyaml` runtime dependencies, and the single `justkernel` entrypoint. CI runs the checker after `uv build`.

**Why:** A clean package and dependency set are part of the migration contract; accidental `.codegraph`/agent files or old dependencies must fail release checks.

**Cost if wrong:** The checker is not a vulnerability scanner or SBOM/signature verifier. `.gitignore` is still included by Hatch's sdist defaults, which is harmless.

## D-068 Migration acceptance

**Decision:** Treat migration acceptance as an e2e flow through the real CLI: synthetic legacy SQLite -> explicit migrate -> LEGACY journal with no active clusters/candidates/boards -> repeat migration idempotently -> old file hash unchanged. Demo replay through the new package remains synthetic with zero model/device calls.

**Why:** Migration success is a behavior of the shipped entrypoint and journal, not just unit-level importer tests.

**Cost if wrong:** Legacy schema coverage is limited to the synthetic table set; no real old database corpus is checked. Demo remains static replay.

## D-069 Recovery chaos drills

**Decision:** Add chaos tests that SIGKILL a process holding an open journal, recover missing global device leases into quarantine, and inject a disk-full `OperationalError` during recovery to prove rollback. Recovery interrupts state and never creates replacement tasks.

**Why:** The recovery matrix must be exercised against process death and partial I/O, not only normal SQLite transactions.

**Cost if wrong:** The disk-full drill uses a failing connection proxy, not a full filesystem; the kill drill is POSIX-only. Real device disconnect/zip interruption remain simulated.

## D-070 100-agent scale drill

**Decision:** Add a deterministic e2e drill with 100 active agents, three Turn cycles (300 turns), 98 worker tasks, one checkpoint per agent, lease acquisition/worker close and full runtime shutdown. Both domain and pool reject the 101st agent; shutdown leaves zero active sessions and zero tracked leases.

**Why:** The scale invariant must be exercised through domain, runtime pool, checkpoint and lease cleanup together, not only by unit caps.

**Cost if wrong:** Drills run sequentially with a fake runner; they do not prove wall-clock endurance, provider concurrency, or real process/memory pressure.

## D-071 Multi-model routing acceptance

**Decision:** Allow `FeedbackHandoffService` to create a replacement optimizer with a different model profile while reusing the same failure feedback/history. E2E acceptance verifies routing priority, configured fallback, per-agent model binding, and unchanged board-free optimizer tools.

**Why:** Changing a worker model must not silently change the task evidence or broaden its permissions.

**Cost if wrong:** No live provider calls or per-turn model/version usage records are exercised here; those remain for real-model acceptance.

## D-072 Real acceptance gate is fail-closed

**Decision:** Real CANN/model acceptance requires an externally produced evidence bundle and `JUSTKERNEL_REAL_ACCEPTANCE_DIR`. The gate rejects `cann-simulation`, fake providers, missing versions/devices, bad digests, non-executed/full/PASS records and absent reports. No bundle means skip, not fake success.

**Why:** The final acceptance cannot be established by synthetic fakes; absent hardware/credentials must remain visibly blocked.

**Cost if wrong:** The gate validates evidence but does not execute the real run. F09-04 remains blocked until an operator supplies a real bundle.

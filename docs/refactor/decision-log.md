# JustKernel v2 Foundation Decision Log

> Scope: P0 decisions that later plans depend on. Each decision records why it was made and what it costs if wrong.
> Status: accepted for P0 unless a later plan records a superseding decision.

## D-001 SQLite access

**Decision:** Use the standard-library `sqlite3` module with explicit SQL. Do not add an ORM in P0/P1.

**Why:** SPEC 08 depends on partial unique indexes, append-only triggers, explicit transaction boundaries, and hand-written event/outbox semantics. An ORM would hide exactly the behavior the architecture tests must prove.

**Cost if wrong:** More SQL and repository boilerplate; a later migration to an ORM would touch every adapter but not the domain.

## D-002 IDs and digests

**Decision:** IDs are UUID4 rendered as 32 lowercase hexadecimal characters. Digests are SHA-256 rendered as 64 lowercase hexadecimal characters.

**Why:** SPEC 04 fixes the ID format; content-addressed artifacts and TestRecord manifests need one digest spelling across Python, SQLite, JSON, and the web UI.

**Cost if wrong:** A format change requires migration/rewrite of every stored ID and artifact path; doing it after evidence exists would be expensive.

## D-003 Canonical JSON

**Decision:** Persisted structured payloads use UTF-8 JSON with sorted keys and compact separators. `NaN` and `Infinity` are rejected in persisted payloads.

**Why:** Idempotency keys, digests, event payloads, and BestSelection records must be reproducible across processes and machines. Non-finite numbers make comparison and persistence ambiguous.

**Cost if wrong:** A digest mismatch or non-reproducible record; fixing it would require a schema version and re-hashing affected artifacts.

## D-004 Configuration boundary

**Decision:** Only `justkernel.platform.config` reads environment variables. Precedence is CLI > environment > `.env` > defaults. Constructors do not create directories; `bootstrap.initialize()` performs explicit setup.

**Why:** SPEC 03 forbids import-time side effects and scattered environment reads. A single boundary makes tests deterministic and lets the CLI/bootstrap own filesystem setup.

**Cost if wrong:** A hidden environment read in a domain module would make tests order-dependent and violate the architecture gate; the fix is centralization, not a domain change.

## D-005 Transitional packages

**Decision:** `src/justkernel` and `src/aworker` coexist through P7. New code must never import `aworker`. P8 removes the old package and switches the distribution/CLI to `justkernel`.

**Why:** A big-bang rewrite would lose the running legacy implementation and its 229-test baseline. Parallel packages let us reuse adapters while keeping the old app runnable for characterization.

**Cost if wrong:** Temporary duplicate code and a larger wheel; P8 must delete the old package and add a hard no-`aworker` CI gate, otherwise the transition becomes permanent.

## D-006 CLI naming

**Decision:** `justkernel` is the only future CLI. `aworker` and `aworker-lab` remain transitional aliases in `pyproject.toml` until P8.

**Why:** SPEC 03/12 require one package and one CLI. Keeping aliases temporarily avoids breaking the legacy app while the new entry point is scaffolded.

**Cost if wrong:** Users may keep invoking aliases; P8 must remove them and update README/scripts/CI in the same cutover.

## D-007 Type checking

**Decision:** Use `mypy` scoped to `src/justkernel` only. Legacy `src/aworker` is not a typing target.

**Why:** SPEC 11 requires a type-check gate, but typing 12k lines of legacy code would block P0 and add no value to the replacement. New code starts typed from the first domain module.

**Cost if wrong:** Type errors can hide at the boundary between new and legacy adapters; P4/P5 adapter tests and runtime contract tests must cover those boundaries.

## D-008 Web tests

**Decision:** New `src/justkernel/web` uses plain ES modules and Node's built-in test runner. Existing `.cjs` web tests remain until P7.

**Why:** SPEC 09 requires no build dependency and live/replay/demo sharing one reducer. Node's built-in runner avoids adding a frontend toolchain.

**Cost if wrong:** If a browser-only behavior cannot be covered by Node tests, P7 may need a small DOM harness; that is additive and does not change the reducer contract.

## P0 execution rulings

These are smaller process decisions made while executing the P0 plan:

- **Branch in place, no worktree:** work happens on `refactor/justkernel-v2` in the existing checkout. The TODO allowed “branch or worktree”; the legacy tree is frozen and the user approved P0 execution. Cost if wrong: the main checkout is on the refactor branch and must be switched back before finishing.
- **CLI scaffold tests in `tests/unit`:** CLI behavior is a unit contract, and the P0 CI command names `tests/unit`; the test was moved from `tests/architecture` to keep that path non-empty and semantically correct. Cost if wrong: one path differs from the original plan text.
- **Baseline prerequisite is explicit:** the report records that `tools/import_official_template.py` must run before the legacy suite. Without it, the baseline shows 117 setup errors rather than real failures. Cost if wrong: a future run misreads missing fixture data as a regression.

# F08-01 Legacy Read-only Import and LEGACY Markers

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Import old lab tables into separate immutable LEGACY records, idempotently, without touching the old database or creating active clusters/boards/candidates.

**Architecture:** Add migration 2 with `legacy_imports`/`legacy_records` and update/delete-blocking triggers. `LegacyImporter` opens the old SQLite file with `mode=ro` and `query_only`, maps teams/runs/experiences/events/members, and records a source digest.

**Spec:** `SPEC/08-persistence-and-events.md` §9; `SPEC/12-migration-and-acceptance.md` §1.

## Global Constraints

- Old database is never modified.
- Repeated import of the same source digest is idempotent.
- Imported rows are `LEGACY`, read-only and cannot become active state/best.
- No old code or test imports.
- Synthetic fixture only.
- No old board/queue activation.

## Files

- Modify: `platform/persistence/schema.py`, `migrations.py`
- Create: `platform/persistence/legacy_import.py`
- Create: `tests/adapters/test_legacy_import.py`
- Modify: `tests/adapters/test_schema.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [x] **Step 1: Add legacy schema/migration and importer**
- [x] **Step 2: Add synthetic old DB fixture/idempotency/immutability tests**
- [x] **Step 3: Verify no active state is created**
- [ ] **Step 4: Record and push**

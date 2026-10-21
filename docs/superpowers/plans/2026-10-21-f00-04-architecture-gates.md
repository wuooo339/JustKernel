# F00-04 Architecture Gates Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add architecture tests that keep the independent `justkernel` project free of legacy imports, side effects, oversized modules, and cross-layer dependencies.

**Architecture:** Tests inspect the source tree and import the package in a subprocess. They are guards, not behavioral features; they must fail when the package skeleton is absent and pass on the current skeleton.

**Spec:** `SPEC/03-architecture.md` §3, `SPEC/11-testing-and-quality.md` §8.

## Global Constraints

- No `aworker` import or compatibility layer.
- Domain modules must not import `justkernel.platform`.
- Import must not create files/directories or read configuration.
- File/function budgets: domain 300, bootstrap 400, platform 600, web 400, function 40.

## Files

- Create: `tests/architecture/test_import_boundaries.py`
- Create: `tests/architecture/test_file_sizes.py`
- Create: `tests/architecture/test_import_has_no_side_effects.py`
- Create: `tests/architecture/test_package_exports.py`
- Create: `tests/architecture/test_no_legacy.py`
- Modify: `TODO.md`
- Modify: `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write the architecture tests**

Create the five test modules. The tests must:
- assert every expected package directory exists;
- reject imports of the legacy name and cross-package relative imports;
- reject `justkernel.platform` imports from domain packages;
- enforce line/function budgets;
- import every module in a temporary cwd/HOME and assert no files are created;
- assert the package has no legacy attribute.

- [ ] **Step 2: Run the gates**

```bash
uv run pytest -q tests/architecture
```

Expected: all pass on the current skeleton.

- [ ] **Step 3: Check the no-legacy scan**

```bash
rg -n "aworker" src tests
```

Expected: no matches. (The test builds the legacy name from fragments so the test file itself does not match.)

- [ ] **Step 4: Verify the rest of the project**

```bash
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

Commit the gate tests, update `TODO.md`/feature log, then:

```bash
scripts/push_refactor.sh
```

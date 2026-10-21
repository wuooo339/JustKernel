# Relocation to Refactor/ Worktree

> Date: 2026-10-21
> Branch: `refactor/justkernel-v2`
> New root: `/home/gresces/Projects/JustKernel/Refactor`
> Legacy root: `/home/gresces/Projects/JustKernel/JustKernel` (`main`, read-only reference)

## 1. What changed

The P0 implementation was moved from the legacy `JustKernel/` checkout into a
second git worktree rooted at `Refactor/`.

```text
/home/gresces/Projects/JustKernel/
├── JustKernel/   # main worktree: legacy aworker implementation (frozen)
└── Refactor/     # refactor/justkernel-v2 worktree: new justkernel project
    ├── SPEC/
    ├── TODO.md
    ├── README.md
    ├── pyproject.toml
    ├── src/justkernel/
    ├── tests/{unit,architecture,characterization}/
    └── docs/{refactor,superpowers}/
```

`Refactor/` is not a second repository. It is a worktree of the same git
history, so commits and the `legacy-baseline` tag remain available from both
roots.

## 2. New project boundary

- `Refactor/pyproject.toml` is `name = "justkernel"`, packages only
  `src/justkernel`, and maps `justkernel` to
  `justkernel.bootstrap.cli:main`.
- `src/aworker` was removed from the new project. The legacy code stays in
  `JustKernel/src/aworker`.
- Old tests, tools, start scripts, browser/judge assets, and old docs were
  removed from the new project; they remain in `JustKernel/`.
- Characterization tests are local-only: `tests/characterization/conftest.py`
  adds `../JustKernel/src` and ignores the legacy modules when the tree is absent.
- CI for the new project runs ruff, mypy, pytest, and `uv build`; it does not
  depend on the legacy repository.

## 3. Verification

Run from `Refactor/`:

```text
uv sync
  -> installed justkernel 0.1.0; removed legacy aworker package

uv run pytest -q
  -> 18 passed (4 unit + 10 architecture + 4 characterization via ../JustKernel)

uv run mypy src/justkernel
  -> success, 21 files

uv run ruff check src tests
  -> all checks passed

uv run ruff format --check src tests
  -> 32 files already formatted

uv run justkernel --version
  -> justkernel 0.1.0

uv build
  -> justkernel-0.1.0.tar.gz
  -> justkernel-0.1.0-py3-none-any.whl (only justkernel modules)
```

Legacy worktree check:

```text
git -C ../JustKernel status --short
  -> empty
git -C ../JustKernel branch --show-current
  -> main
git worktree list
  -> JustKernel  2fa044f [main]
  -> Refactor    15cead8 [refactor/justkernel-v2] (before relocation commit b60e6e4)
```

## 4. Decisions

| Decision | Why | Cost if wrong |
| --- | --- | --- |
| Use a git worktree instead of a separate repo | Keeps one history and the legacy tag; new root is clean | Two worktrees must be explained in docs |
| Delete `src/aworker` from the new project | New code must not depend on the old package | Characterization needs `../JustKernel` locally |
| Keep characterization tests local-only | CI cannot see the sibling legacy tree | Legacy contracts are not checked in CI |
| Name the new project `justkernel` immediately | The new worktree has its own distribution; no transitional alias needed | Users must know which worktree they are in |
| Keep old tests/tools in `JustKernel/` | They remain the legacy baseline and reference | Old app is not maintained in the new project |

## 5. What did not change

- The legacy 229-test baseline remains in `JustKernel/`.
- `Refactor/SPEC/` remains the single architecture source of truth.
- P1 has not started; the new project contains only the P0 skeleton and gates.

## 6. Next step

Write `docs/superpowers/plans/2026-10-21-p1-domain.md` and implement P1:
domain value objects, contracts, aggregates, state machines, ACL, and
invariants under `src/justkernel/`.

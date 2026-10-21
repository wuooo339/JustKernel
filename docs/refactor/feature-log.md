# Feature Log

Remote: `https://github.com/wuooo339/JustKernel.git`  
Target branch: `refactor`  
Local branch: `refactor/justkernel-v2` (`Refactor/` worktree)

This log is the durable evidence trail for the workflow in `TODO.md` §3.1.
Append one row after a feature is tested, committed, and pushed. A feature is
not `done` in `TODO.md` until the push column names the remote commit.

| Feature | Date | Commit | Tests | Push |
| --- | --- | --- | --- | --- |
| F00-01..F00-07 (P0 batch) | 2026-10-21 | `2fa044f..be937f5` | local 18 passed; clean-checkout sim 14 passed; mypy success; ruff clean | `origin/refactor` @ `d5b3d77` (2026-10-21) |

## Append template

```markdown
| F01-01 | 2026-10-21 | `<sha>` | `uv run pytest -q tests/unit/shared` → N passed; full suite N passed; mypy/ruff clean | `origin/refactor` @ `<sha>` |
```

Push note: `origin/refactor` is writable by GitHub account `gresces`; the helper switches to it for the push and restores the active account `secserg` afterward.

Workflow setup commits after the P0 feature push: `049add8` (push log) and `802bbd4` (authenticated push script).

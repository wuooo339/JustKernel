# Feature Log

Remote: `https://github.com/wuooo339/JustKernel.git`  
Target branch: `refactor`  
Local branch: `refactor/justkernel-v2` (`Refactor/` worktree)

A feature is `done` only after its tests pass, it is committed, and the commit is on
`origin/refactor`. Append one row per finished feature.

| Feature | Date | Commit | Tests / Evidence | Push |
| --- | --- | --- | --- | --- |
| F00-01 | 2026-10-21 | `df324b3` | workspace clean: no `src`, no `tests`, no old code; SPEC/TODO/README retained | `origin/refactor` @ `df324b3` |
| F00-02 | 2026-10-21 | `3e75f84` | `uv sync --locked`; 1 test passed; mypy/ruff clean; `uv build` produced justkernel wheel | `origin/refactor` @ `0f3a4a9` |
| F00-03 | 2026-10-21 | `4d9ef9e` | CLI tests 3 passed; mypy/ruff clean; `justkernel --version`; `uv build` | `origin/refactor` (with F00-03 docs commit) |

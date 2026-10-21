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
| F00-03 | 2026-10-21 | `4d9ef9e` | CLI tests 3 passed; mypy/ruff clean; `justkernel --version`; `uv build` | `origin/refactor` @ `2f4a7cd` |
| F00-04 | 2026-10-21 | `f0b0cdc` | architecture 11 passed; full 15 passed; mypy/ruff clean; no legacy literal in src/tests | `origin/refactor` @ `840e852` |
| F00-05 | 2026-10-21 | `5998bf2` | CI workflow; local ruff/mypy/pytest 15 passed/build green | `origin/refactor` @ `5f1d2db` |
| F00-06 | 2026-10-21 | `2888b3d` | decision log D-001..D-010; feature log; P0 exit report; full 15 passed | `origin/refactor` @ `ac4605f` |
| F01-01 | 2026-10-21 | `7c6986c` | shared 19 passed; full 34 passed; mypy/ruff clean; D-011 clock unit | `origin/refactor` (with F01-01 docs commit) |

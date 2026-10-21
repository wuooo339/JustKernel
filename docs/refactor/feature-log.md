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
| F01-01 | 2026-10-21 | `7c6986c` | shared 19 passed; full 34 passed; mypy/ruff clean; D-011 clock unit | `origin/refactor` @ `8b9f0f0` |
| F01-02 | 2026-10-21 | `07549d4` | contract tests 13 passed; full 47 passed; mypy/ruff clean; D-012 | `origin/refactor` @ `2d0ed14` |
| F01-03 | 2026-10-21 | `fa78426` | cluster tests 11 passed; full 58 passed; mypy/ruff clean; D-013 | `origin/refactor` @ `0f190c4` |
| F01-04 | 2026-10-21 | `8854571` | agent tests 10 passed; full 68 passed; mypy/ruff clean; D-014 | `origin/refactor` @ `4a9486f` |
| F01-05 | 2026-10-21 | `daed2a1` | task tests 10 passed; full 78 passed; mypy/ruff clean; D-015 | `origin/refactor` @ `e492c94` |
| F01-06 | 2026-10-21 | `494046d` | candidate tests 13 passed; full 91 passed; mypy/ruff clean; D-016 | `origin/refactor` @ `96f3bbb` |
| F01-07 | 2026-10-21 | `c78099c` | record/lease/report tests 17 passed; full 108 passed; mypy/ruff clean; D-017 | `origin/refactor` @ `0476eb4` |
| F01-08 | 2026-10-21 | `b5b5bc4` | comm tests 23 passed; full 131 passed; mypy/ruff clean; D-018 | `origin/refactor` @ `468f3e5` |
| F01-09 | 2026-10-21 | `8c08d45` (+ registry follow-up) | invariants/events/error-codes/inbox 16 passed; full 147 passed; mypy/ruff clean; D-019 | `origin/refactor` @ `b09ae4f` |
| F02-01 | 2026-10-21 | `5ddaf51` | schema tests 8 passed; full 155 passed; mypy/ruff clean; D-020 | `origin/refactor` @ `6d75319` |
| F02-02 | 2026-10-21 | `baeb079` | UoW/event/outbox tests 5 passed; full 160 passed; mypy/ruff clean; D-021 | `origin/refactor` @ `7c91cf9` |
| F02-03 | 2026-10-21 | `fe99061` | artifact tests 7 passed + error test 1; full 168 passed; mypy/ruff clean; D-022 | `origin/refactor` (with F02-03 docs commit) |

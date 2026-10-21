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
| F02-03 | 2026-10-21 | `fe99061` | artifact tests 7 passed + error test 1; full 168 passed; mypy/ruff clean; D-022 | `origin/refactor` @ `d0c8560` |
| F02-04 | 2026-10-21 | `7843d76` | projection tests 3 passed; full 171 passed; live/replay snapshots match; D-023 | `origin/refactor` @ `25b7e93` |
| F02-05 | 2026-10-21 | `b044126` | registry tests 8 passed; full 179 passed; mypy/ruff clean; D-024 | `origin/refactor` @ `d3e3303` |
| F02-06 | 2026-10-21 | `a8a88e5` | hardware ledger tests 9 passed; full 188 passed; mypy/ruff clean; D-025 | `origin/refactor` @ `4e01e03` |
| F02-07 | 2026-10-21 | `cc558e1` | recovery tests 2 passed; full 190 passed; mypy/ruff clean; D-026 | `origin/refactor` @ `8a065f9` |
| F02-08 | 2026-10-21 | `4c2818b` | adapters 43 passed; full 191 passed; mypy/ruff clean; cross-adapter suite | `origin/refactor` @ `08a382d` |
| F03-01 | 2026-10-21 | `8ac9def` | ports/fakes tests 7 passed; full 198 passed; mypy/ruff clean; D-027 | `origin/refactor` @ `d576d36` |
| F03-02 | 2026-10-21 | `f7a04a0` | cluster lifecycle tests 5 passed; full 203 passed; mypy/ruff clean; D-028 | `origin/refactor` @ `bcc5acf` |
| F03-03 | 2026-10-21 | `906390d` | worker lifecycle tests 6 passed; full 209 passed; mypy/ruff clean; D-029 | `origin/refactor` @ `d2b2652` |
| F03-04 | 2026-10-21 | `538b247` | candidate tests 7 passed; full 216 passed; mypy/ruff clean; D-030 | `origin/refactor` @ `b371668` |
| F03-05 | 2026-10-21 | `cd11af8` | testing flow tests 5 passed; full 221 passed; mypy/ruff clean; D-031 | `origin/refactor` @ `f0e33ce` |
| F03-06 | 2026-10-21 | `de3cf5d` | best/report/budget tests 6 passed; full 227 passed; mypy/ruff clean; D-032 | `origin/refactor` @ `815293c` |
| F03-07 | 2026-10-21 | `869f099` | ACL/ownership/idempotency tests 6 passed; full 233 passed; mypy/ruff clean | `origin/refactor` @ `41f14af` |
| F04-01 | 2026-10-21 | `704710c` | model routing tests 6 passed; full 239 passed; mypy/ruff clean; D-033 | `origin/refactor` @ `76220a1` |
| F04-02 | 2026-10-21 | `a5df37f` | runtime pool tests 7 passed; full 246 passed; mypy/ruff clean; D-034 | `origin/refactor` @ `e472e90` |
| F04-03 | 2026-10-21 | `d999243` | skill tests 7 passed; full 253 passed; mypy/ruff clean; D-035 | `origin/refactor` @ `19c64c6` |
| F04-04 | 2026-10-21 | `0c30d71` | role-skills tests 3 passed; full 256 passed; mypy/ruff clean; D-036 | `origin/refactor` @ `053f1d1` |
| F04-05 | 2026-10-21 | `a2c50f4` | tool-registry tests 6 passed; full 262 passed; mypy/ruff clean; D-037 | `origin/refactor` @ `1d3ffd6` |
| F04-06 | 2026-10-21 | `4f002c7` | lifecycle tests 3 passed; full 265 passed; mypy/ruff clean; D-038; P4 exit report | `origin/refactor` @ `ebc475d` |
| F05-01 | 2026-10-21 | `92c8768` | tool-job tests 7 passed; full 272 passed; mypy/ruff clean; D-039 | `origin/refactor` @ `8959bd7` |
| F05-02 | 2026-10-21 | `dff7b7e` | hardware-queue tests 6 passed; full 278 passed; mypy/ruff clean; D-040 | `origin/refactor` @ `f69b8d7` |
| F05-03 | 2026-10-21 | `dca59d4` | record-zip tests 12 passed; full 290 passed; mypy/ruff clean; D-041 | `origin/refactor` (with F05-03 docs commit) |

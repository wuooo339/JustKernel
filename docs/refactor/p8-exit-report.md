# P8 Exit Report

Date: 2026-10-21  
Project: `Refactor/` independent `justkernel`  
Remote: `origin/refactor`

## Completed features

| Feature | Commit | Evidence |
| --- | --- | --- |
| F08-01 Legacy read-only import | `3084021` | 2 legacy tests; D-063 |
| F08-02 CLI modes and configuration | `e4fef3c` | 5 config/CLI tests; D-064 |
| F08-03 Data root, permissions, service lock | `50b8035` | 3 data-root tests; D-065 |
| F08-04 No legacy references | `ad8a951` | 4 architecture tests; D-066 |
| F08-05 Packaging and supply-chain gate | `471f8a2` | 3 packaging tests + dist checker; D-067 |
| F08-06 Migration/compatibility acceptance | `5a1fcb7` | 2 e2e migration/demo tests; D-068 |

## Exit criteria

- [x] Legacy data imports read-only and idempotently.
- [x] Imported data is LEGACY/read-only and not active clusters/candidates/boards.
- [x] CLI modes cluster/demo/worker/migrate resolve config with correct precedence.
- [x] Migrate explicitly requires a legacy database.
- [x] Data root directories are 0700 and files 0600.
- [x] Second service owner is rejected by the single-service lock.
- [x] No legacy package/CLI/env references in source, tests or package metadata.
- [x] Wheel/sdist exclude local agent/index state and old names.
- [x] Runtime dependency set is allowlisted and entrypoint is unique.
- [x] Demo replay remains synthetic with zero model/device calls.
- [x] Migration and new-package compatibility pass end-to-end.

## Verification at P8 exit

```text
uv run pytest -q
407 passed

node --test tests/web
17 passed

uv run mypy src/justkernel
Success: no issues found in 134 source files

uv run ruff check src tests
All checks passed!

uv run ruff format --check src tests
223 files already formatted

uv build
justkernel-0.1.0.tar.gz
justkernel-0.1.0-py3-none-any.whl

uv run python scripts/check_dist.py
checked wheel and sdist
```

## Scope and limitations

P8 proves migration, configuration, packaging and compatibility gates. Legacy mapping
covers the synthetic table set (`teams/members/runs/experiences/events`), not an
arbitrary historical corpus. The cluster/demo/worker CLI modes still print resolved
configuration rather than launching the control plane/server. Single-service locking
is filesystem-local and advisory. Real CANN/model acceptance remains P9.

## Next

P9 starts with **F09-01 Chaos and recovery drills**.

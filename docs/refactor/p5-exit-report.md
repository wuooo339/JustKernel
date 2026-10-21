# P5 Exit Report

Date: 2026-10-21  
Project: `Refactor/` independent `justkernel`  
Remote: `origin/refactor`

## Completed features

| Feature | Commit | Evidence |
| --- | --- | --- |
| F05-01 Async ToolJob service | `92c8768` | 7 lifecycle/timeout tests; D-039 |
| F05-02 Hardware queue/lease/fencing | `dff7b7e` | 6 queue/TTL/quarantine tests; D-040 |
| F05-03 TestRecord zip | `dca59d4` | 12 build/validation/audit tests; D-041 |
| F05-04 CANN simulation backend | `cdbe123` | 7 contract/fingerprint tests; D-042 |
| F05-05 TaskContext artifact grants | `9c83732` | 7 authorization/expiry tests; D-043 |
| F05-06 Evidence chain | `74b40ee` | 4 chain/no-fake-PASS tests; D-044 |

## Exit criteria

- [x] ToolJob submit is idempotent and conflicting parameters are rejected.
- [x] Queue/execution timeouts terminate jobs without overwriting terminal state.
- [x] Hardware queue enforces one lease per device, TTL and fencing.
- [x] Active expired execution stays quarantined until confirmed stopped.
- [x] TestRecord zips are deterministic, checksummed, path-safe and auditable.
- [x] Audit records cannot claim execution or PASS.
- [x] CANN simulation backend captures requests and environment fingerprints.
- [x] TaskContext binds task/candidate and only owner can read it.
- [x] Artifact grants enforce digest, read-only scope and expiry.
- [x] Best nomination revalidates the archive and rejects fabricated PASS records.
- [x] Full suite passes without real devices or subprocesses.

## Verification at P5 exit

```text
uv run pytest -q tests/application/test_evidence_chain.py
4 passed

uv run pytest -q
308 passed

uv run mypy src/justkernel
Success: no issues found in 106 source files

uv run ruff check src tests
All checks passed!

uv run ruff format --check src tests
174 files already formatted

uv build
justkernel-0.1.0.tar.gz
justkernel-0.1.0-py3-none-any.whl
```

## Scope and limitations

P5 establishes the async job, hardware queue, archive, backend, context-grant and
best-evidence contracts. The CANN backend is a deterministic fake; archive payloads
are assembled by callers, and no HTTP/control orchestration is included yet. Real CANN
command execution, automatic evidence packaging, control/UI wiring and cluster
bootstrap are P6+ work.

## Next

P6 starts with **F06-01 OperatorSpec startup validation and cluster start**.

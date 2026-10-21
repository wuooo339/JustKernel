# F09-04 Real CANN and Real Model Acceptance Gate

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Accept a real CANN/real-model run only when an external evidence bundle is explicitly supplied; never substitute fake simulation evidence.

**Architecture:** An opt-in e2e test reads `JUSTKERNEL_REAL_ACCEPTANCE_DIR`, validates a bundle manifest, real record zip, digest, backend/environment and report. Missing evidence skips; malformed or fake evidence fails.

**Spec:** `SPEC/13-generation-and-iteration-contract.md` §10; `SPEC/12-migration-and-acceptance.md` §3 Phase 6.

## Global Constraints

- No `cann-simulation` or fake model may satisfy real acceptance.
- Evidence must be executed, full-coverage PASS with a valid zip.
- Model provider/version and CANN/device environment must be present.
- No evidence bundle -> skip with an explicit reason.
- Supplied but invalid evidence -> fail.
- No old-code imports/tests.

## Files

- Create: `tests/e2e/test_real_acceptance.py`
- Modify: `TODO.md` (block F09-04 until external bundle exists)
- Create: `docs/refactor/real-acceptance-requirements.md`

## Status

**Blocked:** this workspace has no CANN/NPU tooling or model credentials. Do not mark
F09-04 done until a real bundle is supplied and accepted.

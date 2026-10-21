# F05-06 Evidence Chain: Candidate → Job → Zip → Record

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Prove a real evidence chain from candidate/task through an executed ToolJob, validated zip archive, sealed TestRecord, and best nomination; reject manually fabricated PASS records.

**Architecture:** `EvidenceChainService` creates a record id, builds a draft record/archive, validates and stores the archive, then seals the real record with `TestingService`. `EvidenceGate` revalidates stored archives and manifest/record consistency before `BestSelectionService` accepts evidence.

**Spec:** `SPEC/07-testing-and-profile.md` §3; `SPEC/11-testing-and-quality.md` §3.

## Global Constraints

- A PASS nomination requires `executed=true`, `coverage=FULL`, `outcome=PASS`.
- The artifact must exist, validate, and match the record id/candidate/task/job/skill/outcome.
- A fabricated PASS record with no valid archive is rejected.
- Zip validation remains mandatory; no fake PASS bypass.
- Existing services keep their current behavior when no evidence gate is configured.
- No old-code imports/tests.

## Files

- Modify: `src/justkernel/application/testing_service.py` — optional record id for sealed records
- Create: `src/justkernel/application/evidence_chain.py` — `EvidenceChainService`, `EvidenceGate`
- Modify: `src/justkernel/application/best_report_service.py` — optional evidence gate
- Create: `tests/application/test_evidence_chain.py`
- Create: `docs/refactor/p5-exit-report.md`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write failing evidence-chain tests**

Cover real candidate/task/job execution, archive store, sealed full PASS, best nomination, fabricated PASS rejection, and non-PASS evidence.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_evidence_chain.py
```

Expected: missing evidence service.

- [ ] **Step 3: Implement**

Keep archive validation before sealing and again before best selection. Do not expose a fake record shortcut.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_evidence_chain.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: P5 exit report, commit, push**

# F03-06 BestSelection, Report, and Budget Use Cases Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`) syntax.

**Goal:** Implement best-candidate nomination/final validation, exploration report writing, and an idempotent reserve/settle budget ledger.

**Architecture:** `application/best_report_service.py` depends on cluster/candidate/record/best/report repository ports and `IdFactoryPort`. `BudgetLedgerPort` and `InMemoryBudgetLedger` provide reserve/settle semantics. All evidence checks use full-PASS TestRecords.

**Spec:** `SPEC/07-testing-and-profile.md` §7; `SPEC/13-generation-and-iteration-contract.md` §6–7.

## Global Constraints

- Best nomination requires evidence records for the candidate; full TEST PASS is required.
- Final validation requires final records for the candidate and full PASS.
- BestSelection transitions only PENDING → VALIDATED/FAILED via the domain.
- Reports reference existing same-cluster candidates and records.
- Budget reserve is idempotent by key; settle converts reserved to consumed; insufficient budget returns false.
- Application imports ports/domain only, never platform.
- No old-code imports or old tests.

## Files

- Modify: `src/justkernel/application/ports.py` — best/report/budget ports
- Modify: `src/justkernel/application/fakes.py` — in-memory repositories + budget ledger
- Create: `src/justkernel/application/best_report_service.py` — `BestSelectionService`, `ReportService`
- Create: `tests/application/test_best_report.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Interfaces

```python
class BestSelectionRepositoryPort(Protocol):
    def insert(self, selection: BestSelection) -> None: ...
    def update(self, selection: BestSelection) -> None: ...
    def get(self, selection_id: BestSelectionId) -> BestSelection: ...

class ReportRepositoryPort(Protocol):
    def append(self, report: ExplorationReport) -> None: ...
    def get(self, report_id: str) -> ExplorationReport: ...

class BudgetLedgerPort(Protocol):
    def reserve(self, cluster_id, amount, idempotency_key) -> bool: ...
    def settle(self, cluster_id, amount, idempotency_key) -> bool: ...
    def available(self, cluster_id) -> int: ...

class BestSelectionService:
    def nominate_best(...) -> BestSelection: ...
    def validate_best(...) -> BestSelection: ...

class ReportService:
    def write_report(...) -> ExplorationReport: ...
```

## Steps

- [ ] **Step 1: Write failing tests**

`tests/application/test_best_report.py`:
- nomination with full PASS evidence; reject missing/wrong-candidate evidence;
- final validation with full PASS final record; reject non-full-pass;
- report with existing candidates/records; reject unknown candidate;
- budget reserve/settle/idempotency/insufficient.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_best_report.py
```

Expected: import failure for missing service/ports.

- [ ] **Step 3: Implement**

Add ports/fakes, then the services and budget ledger.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_best_report.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
```

- [ ] **Step 5: Commit, record, push**

```bash
scripts/push_refactor.sh
```

# F06-04 Feedback Handoff and Worker Replacement

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Build an immutable feedback package from a failed TestRecord, close the old optimizer, open a new optimizer, and dispatch a new OPTIMIZE task whose TaskContext contains the failure evidence and retry link.

**Architecture:** `FeedbackHandoffService` composes AgentService, candidate/TestRecord repositories, and TaskContext. It preallocates the new TaskId, builds the context, closes the old idle worker, opens a replacement, and calls `assign_task` with the same context digest and `retry_of_task_id`.

**Spec:** `SPEC/13-generation-and-iteration-contract.md` §3; `SPEC/01-product-vision.md` QA-17.

## Global Constraints

- The new TaskContext contains the failed record/case feedback and the prior candidate history.
- The old worker must be closed before the new one is opened.
- The old worker must not be running a task; a running task is failed through AgentService first.
- The new worker receives no extra board/record privileges.
- The new task links `retry_of_task_id` to the old task.
- The old context/task/record remain available; nothing is overwritten.
- No old-code imports/tests.

## Files

- Modify: `src/justkernel/application/agent_service.py` — optional task id and `fail_task`
- Create: `src/justkernel/application/feedback_handoff_service.py`
- Modify: `src/justkernel/shared/error_codes.py` — handoff error
- Create: `tests/application/test_feedback_handoff.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [ ] **Step 1: Write failing handoff tests**

Cover feedback fields, history, new worker/task, retry link, closing the old worker, and rejection when the old worker is still running without a matching task.

- [ ] **Step 2: Run RED**

```bash
uv run pytest -q tests/application/test_feedback_handoff.py
```

- [ ] **Step 3: Implement**

Validate old worker/task/candidate/record ownership before closing anything. Preserve the original context digest/record references.

- [ ] **Step 4: Run GREEN and full verification**

```bash
uv run pytest -q tests/application/test_feedback_handoff.py
uv run pytest -q
uv run mypy src/justkernel
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

- [ ] **Step 5: Commit, record, push**

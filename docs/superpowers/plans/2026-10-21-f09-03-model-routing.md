# F09-03 Multi-model Routing Acceptance

> **For agentic workers:** Use superpowers:executing-plans inline. Steps use checkbox (`[ ]`).

**Goal:** Verify role/instance/direction/task routing, configured fallback, model-bound agents, and feedback-preserving model switch with unchanged optimizer ACL.

**Architecture:** E2E test composes `ModelRoutingService`, `AgentService` and `FeedbackHandoffService`; handoff accepts an optional model override while reusing the same TaskContext feedback/history.

**Spec:** `SPEC/13-generation-and-iteration-contract.md` §9.

## Global Constraints

- Priority: instance > task > direction > role > system.
- Fallback uses only configured profiles; agent profile fixed at creation.
- Model switch creates a new worker and preserves feedback/history.
- Model differences do not change ACL.
- No old-code imports/tests.

## Files

- Modify: `application/feedback_handoff_service.py` — optional model override
- Create: `tests/e2e/test_model_routing_acceptance.py`
- Modify: `TODO.md`, `docs/refactor/feature-log.md`

## Steps

- [x] **Step 1: Add optional handoff model override**
- [x] **Step 2: Add routing/fallback/handoff acceptance**
- [ ] **Step 3: Record and push**

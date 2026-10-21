"""Stable machine-readable error codes."""

from __future__ import annotations

from enum import StrEnum


# ---- ErrorCode --------------------------------------------------------------
class ErrorCode(StrEnum):
    JUSTKERNEL_ERROR = "justkernel_error"
    INVALID_ID = "invalid_id"
    INVALID_DIGEST = "invalid_digest"
    INVALID_JSON = "invalid_json"
    INVALID_CLOCK = "invalid_clock"
    INVALID_PRINCIPAL = "invalid_principal"
    INVALID_PROJECT_PATH = "invalid_project_path"
    INVALID_POLICY = "invalid_policy"
    OPERATOR_SPEC_INCOMPLETE = "operator_spec.incomplete"
    INVALID_CLUSTER_TRANSITION = "invalid_cluster_transition"
    INVALID_DIRECTION_TRANSITION = "invalid_direction_transition"
    INVALID_AGENT_TRANSITION = "invalid_agent_transition"
    INVALID_TASK_TRANSITION = "invalid_task_transition"
    INVALID_TASK_CONTEXT = "invalid_task_context"
    INVALID_CANDIDATE = "invalid_candidate"
    INVALID_BEST_SELECTION = "invalid_best_selection"
    INVALID_TEST_RECORD = "invalid_test_record"
    INVALID_LEASE_TRANSITION = "invalid_lease_transition"
    INVALID_REPORT = "invalid_report"
    INVALID_CHANNEL = "invalid_channel"
    ACL_DENIED = "acl.denied"
    INVALID_MESSAGE = "invalid_message"
    INVALID_EVENT = "invalid_event"
    INVARIANT_VIOLATION = "invariant.violation"

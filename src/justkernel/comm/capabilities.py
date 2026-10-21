"""Role-to-tool capability matrix."""

from __future__ import annotations

from enum import StrEnum

from justkernel.agent.state import Role


# ---- Tool -------------------------------------------------------------------
class Tool(StrEnum):
    READ_MENTOR_BOARD = "read_mentor_board"
    POST_MENTOR_BOARD = "post_mentor_board"
    READ_CONSULTANT_BOARD = "read_consultant_board"
    POST_CONSULTANT_BOARD = "post_consultant_board"
    SEND_BRIEF = "send_brief"
    READ_CLUSTER = "read_cluster"
    OPEN_WORKER = "open_worker"
    CLOSE_WORKER = "close_worker"
    ASSIGN_TASK = "assign_task"
    READ_TASK = "read_task"
    READ_TASK_CONTEXT = "read_task_context"
    READ_TASK_ARTIFACT = "read_task_artifact"
    READ_TOOL_JOB = "read_tool_job"
    READ_CANDIDATE = "read_candidate"
    WRITE_SOURCE = "write_source"
    COMMIT_CANDIDATE = "commit_candidate"
    SUBMIT_TEST = "submit_test"
    SUBMIT_PROFILE = "submit_profile"
    READ_TEST_RECORD = "read_test_record"
    QUEUE_STATUS = "queue_status"
    SELECT_BEST = "select_best"
    WRITE_REPORT = "write_report"
    REPORT_PROGRESS = "report_progress"


BOARD_TOOLS = frozenset(
    {
        Tool.READ_MENTOR_BOARD,
        Tool.POST_MENTOR_BOARD,
        Tool.READ_CONSULTANT_BOARD,
        Tool.POST_CONSULTANT_BOARD,
        Tool.SEND_BRIEF,
    }
)

TOOL_MATRIX: dict[Tool, frozenset[Role]] = {
    Tool.READ_MENTOR_BOARD: frozenset({Role.SUPERVISOR, Role.MENTOR, Role.CONSULTANT}),
    Tool.POST_MENTOR_BOARD: frozenset({Role.SUPERVISOR, Role.MENTOR}),
    Tool.READ_CONSULTANT_BOARD: frozenset({Role.SUPERVISOR, Role.CONSULTANT}),
    Tool.POST_CONSULTANT_BOARD: frozenset({Role.SUPERVISOR, Role.CONSULTANT}),
    Tool.SEND_BRIEF: frozenset({Role.CONSULTANT}),
    Tool.READ_CLUSTER: frozenset({Role.SUPERVISOR, Role.CONSULTANT, Role.MENTOR}),
    Tool.OPEN_WORKER: frozenset({Role.MENTOR}),
    Tool.CLOSE_WORKER: frozenset({Role.MENTOR}),
    Tool.ASSIGN_TASK: frozenset({Role.MENTOR}),
    Tool.READ_TASK: frozenset({Role.MENTOR, Role.OPTIMIZER, Role.TESTER, Role.PROFILER}),
    Tool.READ_TASK_CONTEXT: frozenset({Role.MENTOR, Role.OPTIMIZER, Role.TESTER, Role.PROFILER}),
    Tool.READ_TASK_ARTIFACT: frozenset({Role.MENTOR, Role.OPTIMIZER, Role.TESTER, Role.PROFILER}),
    Tool.READ_TOOL_JOB: frozenset({Role.MENTOR, Role.TESTER, Role.PROFILER}),
    Tool.READ_CANDIDATE: frozenset(
        {Role.SUPERVISOR, Role.MENTOR, Role.OPTIMIZER, Role.TESTER, Role.PROFILER}
    ),
    Tool.WRITE_SOURCE: frozenset({Role.OPTIMIZER}),
    Tool.COMMIT_CANDIDATE: frozenset({Role.OPTIMIZER}),
    Tool.SUBMIT_TEST: frozenset({Role.TESTER}),
    Tool.SUBMIT_PROFILE: frozenset({Role.PROFILER}),
    Tool.READ_TEST_RECORD: frozenset({Role.SUPERVISOR, Role.MENTOR, Role.TESTER, Role.PROFILER}),
    Tool.QUEUE_STATUS: frozenset({Role.SUPERVISOR, Role.MENTOR, Role.TESTER, Role.PROFILER}),
    Tool.SELECT_BEST: frozenset({Role.SUPERVISOR}),
    Tool.WRITE_REPORT: frozenset({Role.SUPERVISOR}),
    Tool.REPORT_PROGRESS: frozenset(Role),
}


# ---- tools_for --------------------------------------------------------------
def tools_for(role: Role) -> frozenset[Tool]:
    return frozenset(tool for tool, roles in TOOL_MATRIX.items() if role in roles)


# ---- can_use_tool -----------------------------------------------------------
def can_use_tool(role: Role, tool: Tool) -> bool:
    return role in TOOL_MATRIX.get(tool, frozenset())

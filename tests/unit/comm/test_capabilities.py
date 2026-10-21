from __future__ import annotations

from justkernel.agent.state import WORKER_ROLES, Role
from justkernel.comm.capabilities import BOARD_TOOLS, Tool, can_use_tool, tools_for


# ---- role/tool matrix -------------------------------------------------------
def test_supervisor_capabilities() -> None:
    assert can_use_tool(Role.SUPERVISOR, Tool.SELECT_BEST)
    assert can_use_tool(Role.SUPERVISOR, Tool.WRITE_REPORT)
    assert can_use_tool(Role.SUPERVISOR, Tool.POST_MENTOR_BOARD)
    assert not can_use_tool(Role.SUPERVISOR, Tool.OPEN_WORKER)
    assert not can_use_tool(Role.SUPERVISOR, Tool.WRITE_SOURCE)


def test_consultant_is_read_only_on_mentor_board() -> None:
    assert can_use_tool(Role.CONSULTANT, Tool.READ_MENTOR_BOARD)
    assert not can_use_tool(Role.CONSULTANT, Tool.POST_MENTOR_BOARD)
    assert can_use_tool(Role.CONSULTANT, Tool.POST_CONSULTANT_BOARD)
    assert can_use_tool(Role.CONSULTANT, Tool.SEND_BRIEF)


def test_mentor_owns_worker_and_task_tools() -> None:
    assert can_use_tool(Role.MENTOR, Tool.OPEN_WORKER)
    assert can_use_tool(Role.MENTOR, Tool.CLOSE_WORKER)
    assert can_use_tool(Role.MENTOR, Tool.ASSIGN_TASK)
    assert can_use_tool(Role.MENTOR, Tool.READ_TEST_RECORD)
    assert not can_use_tool(Role.MENTOR, Tool.SUBMIT_TEST)


def test_worker_roles_have_no_board_tools() -> None:
    for role in WORKER_ROLES:
        assert not (tools_for(role) & BOARD_TOOLS)


def test_worker_submit_tools_are_role_specific() -> None:
    assert can_use_tool(Role.OPTIMIZER, Tool.WRITE_SOURCE)
    assert can_use_tool(Role.OPTIMIZER, Tool.COMMIT_CANDIDATE)
    assert not can_use_tool(Role.OPTIMIZER, Tool.SUBMIT_TEST)

    assert can_use_tool(Role.TESTER, Tool.SUBMIT_TEST)
    assert not can_use_tool(Role.TESTER, Tool.SUBMIT_PROFILE)

    assert can_use_tool(Role.PROFILER, Tool.SUBMIT_PROFILE)
    assert not can_use_tool(Role.PROFILER, Tool.SUBMIT_TEST)

    assert can_use_tool(Role.TESTER, Tool.QUEUE_STATUS)
    assert can_use_tool(Role.PROFILER, Tool.QUEUE_STATUS)

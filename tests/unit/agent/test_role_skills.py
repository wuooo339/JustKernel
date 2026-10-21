from __future__ import annotations

from pathlib import Path

from justkernel.agent.skill_loader import SkillLoader
from justkernel.agent.state import WORKER_ROLES, Role
from justkernel.comm.capabilities import BOARD_TOOLS, Tool, can_use_tool

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "src" / "justkernel" / "resources" / "skills"

BASE_NAMES = {
    Role.SUPERVISOR: "supervisor",
    Role.CONSULTANT: "consultant",
    Role.MENTOR: "mentor",
    Role.OPTIMIZER: "optimizer",
    Role.TESTER: "tester",
    Role.PROFILER: "profiler",
}

BASE_TOOLS = {
    Role.SUPERVISOR: {
        Tool.READ_MENTOR_BOARD,
        Tool.POST_MENTOR_BOARD,
        Tool.READ_CONSULTANT_BOARD,
        Tool.POST_CONSULTANT_BOARD,
        Tool.READ_CLUSTER,
        Tool.READ_CANDIDATE,
        Tool.READ_TEST_RECORD,
        Tool.QUEUE_STATUS,
        Tool.SELECT_BEST,
        Tool.WRITE_REPORT,
        Tool.REPORT_PROGRESS,
    },
    Role.CONSULTANT: {
        Tool.READ_MENTOR_BOARD,
        Tool.READ_CONSULTANT_BOARD,
        Tool.POST_CONSULTANT_BOARD,
        Tool.SEND_BRIEF,
        Tool.READ_CLUSTER,
        Tool.REPORT_PROGRESS,
    },
    Role.MENTOR: {
        Tool.READ_MENTOR_BOARD,
        Tool.POST_MENTOR_BOARD,
        Tool.READ_CLUSTER,
        Tool.OPEN_WORKER,
        Tool.CLOSE_WORKER,
        Tool.ASSIGN_TASK,
        Tool.READ_TASK,
        Tool.READ_TASK_CONTEXT,
        Tool.READ_TASK_ARTIFACT,
        Tool.READ_TOOL_JOB,
        Tool.READ_CANDIDATE,
        Tool.READ_TEST_RECORD,
        Tool.QUEUE_STATUS,
        Tool.REPORT_PROGRESS,
    },
    Role.OPTIMIZER: {
        Tool.READ_TASK,
        Tool.READ_TASK_CONTEXT,
        Tool.READ_TASK_ARTIFACT,
        Tool.READ_CANDIDATE,
        Tool.WRITE_SOURCE,
        Tool.COMMIT_CANDIDATE,
        Tool.REPORT_PROGRESS,
    },
    Role.TESTER: {
        Tool.READ_TASK,
        Tool.READ_TASK_CONTEXT,
        Tool.READ_TASK_ARTIFACT,
        Tool.READ_TOOL_JOB,
        Tool.READ_CANDIDATE,
        Tool.SUBMIT_TEST,
        Tool.READ_TEST_RECORD,
        Tool.QUEUE_STATUS,
        Tool.REPORT_PROGRESS,
    },
    Role.PROFILER: {
        Tool.READ_TASK,
        Tool.READ_TASK_CONTEXT,
        Tool.READ_TASK_ARTIFACT,
        Tool.READ_TOOL_JOB,
        Tool.READ_CANDIDATE,
        Tool.SUBMIT_PROFILE,
        Tool.READ_TEST_RECORD,
        Tool.QUEUE_STATUS,
        Tool.REPORT_PROGRESS,
    },
}


# ---- loader ----------------------------------------------------------------
def _loader() -> SkillLoader:
    return SkillLoader(SKILLS / "base", SKILLS / "builtin", SKILLS / "user")


def _skills(role: Role) -> dict[str, object]:
    return {skill.name: skill for skill in _loader().load(role)}


# ---- base skills ------------------------------------------------------------
def test_all_six_base_role_skills_load() -> None:
    for role in Role:
        skills = _skills(role)
        base = skills[BASE_NAMES[role]]

        assert base.role is role
        assert base.description
        assert base.backend == "agent"
        assert base.version == "1"
        assert base.allowed_tools == BASE_TOOLS[role]
        assert base.to_ref().digest == base.digest
        assert base.scripts == ()
        assert all(can_use_tool(role, tool) for tool in base.allowed_tools)


def test_tester_and_profiler_include_builtin_skills() -> None:
    tester = _skills(Role.TESTER)
    profiler = _skills(Role.PROFILER)

    assert "cann-simulation-test" in tester
    assert tester["cann-simulation-test"].backend == "cann-simulation"
    assert tester["cann-simulation-test"].allowed_tools == {
        Tool.READ_CANDIDATE,
        Tool.SUBMIT_TEST,
        Tool.READ_TOOL_JOB,
        Tool.READ_TEST_RECORD,
        Tool.REPORT_PROGRESS,
    }

    assert "cann-profiler" in profiler
    assert profiler["cann-profiler"].backend == "cann-profiler"
    assert profiler["cann-profiler"].allowed_tools == {
        Tool.READ_CANDIDATE,
        Tool.SUBMIT_PROFILE,
        Tool.READ_TOOL_JOB,
        Tool.READ_TEST_RECORD,
        Tool.REPORT_PROGRESS,
    }


def test_worker_skills_have_no_board_tools() -> None:
    for role in WORKER_ROLES:
        for skill in _skills(role).values():
            assert not (skill.allowed_tools & BOARD_TOOLS)

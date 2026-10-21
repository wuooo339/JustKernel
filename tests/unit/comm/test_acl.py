from __future__ import annotations

import pytest

from justkernel.agent.state import Role
from justkernel.comm.acl import can_read, can_write, require_read, require_write
from justkernel.comm.channels import Channel
from justkernel.comm.errors import AccessDeniedError
from justkernel.shared.ids import AgentId
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _actor(role: Role) -> tuple[Role, Principal]:
    return role, Principal.agent(AgentId.generate())


# ---- boards -----------------------------------------------------------------
def test_mentor_board_acl() -> None:
    board = Channel.mentor_board()

    assert can_read(*_actor(Role.SUPERVISOR), board)
    assert can_write(*_actor(Role.SUPERVISOR), board)
    assert can_read(*_actor(Role.MENTOR), board)
    assert can_write(*_actor(Role.MENTOR), board)
    assert can_read(*_actor(Role.CONSULTANT), board)
    assert not can_write(*_actor(Role.CONSULTANT), board)
    assert not can_read(*_actor(Role.OPTIMIZER), board)


def test_consultant_board_acl() -> None:
    board = Channel.consultant_board()

    assert can_read(*_actor(Role.SUPERVISOR), board)
    assert can_write(*_actor(Role.SUPERVISOR), board)
    assert can_read(*_actor(Role.CONSULTANT), board)
    assert can_write(*_actor(Role.CONSULTANT), board)
    assert not can_read(*_actor(Role.MENTOR), board)


# ---- worker channel ---------------------------------------------------------
def test_worker_channel_is_private_to_participants() -> None:
    mentor = AgentId.generate()
    worker = AgentId.generate()
    channel = Channel.worker(mentor, worker)
    mentor_actor = Principal.agent(mentor)
    worker_actor = Principal.agent(worker)
    other_mentor = Principal.agent(AgentId.generate())

    assert can_read(Role.MENTOR, mentor_actor, channel)
    assert can_write(Role.MENTOR, mentor_actor, channel)
    assert can_read(Role.OPTIMIZER, worker_actor, channel)
    assert can_write(Role.OPTIMIZER, worker_actor, channel)
    assert not can_read(Role.MENTOR, other_mentor, channel)
    assert not can_read(Role.SUPERVISOR, Principal.agent(AgentId.generate()), channel)


# ---- hardware queue ---------------------------------------------------------
def test_hardware_queue_acl() -> None:
    queue = Channel.hardware()

    assert can_read(*_actor(Role.TESTER), queue)
    assert can_write(*_actor(Role.TESTER), queue)
    assert can_read(*_actor(Role.PROFILER), queue)
    assert can_write(*_actor(Role.PROFILER), queue)
    assert can_read(*_actor(Role.SUPERVISOR), queue)
    assert not can_write(*_actor(Role.SUPERVISOR), queue)
    assert can_read(*_actor(Role.MENTOR), queue)
    assert not can_write(*_actor(Role.MENTOR), queue)
    assert not can_read(*_actor(Role.OPTIMIZER), queue)


# ---- human/system and denial errors ----------------------------------------
def test_human_can_read_but_not_write_and_system_can_write() -> None:
    board = Channel.mentor_board()
    human = Principal.human()
    system = Principal.system()

    assert can_read(Role.SUPERVISOR, human, board)
    assert not can_write(Role.SUPERVISOR, human, board)
    assert can_read(Role.SUPERVISOR, system, board)
    assert can_write(Role.SUPERVISOR, system, board)


def test_require_access_raises() -> None:
    board = Channel.mentor_board()
    consultant = _actor(Role.CONSULTANT)

    require_read(*consultant, board)
    with pytest.raises(AccessDeniedError):
        require_write(*consultant, board)

    with pytest.raises(AccessDeniedError):
        require_read(*_actor(Role.OPTIMIZER), board)

from __future__ import annotations

import pytest

from justkernel.comm.channels import Channel, ChannelKind
from justkernel.comm.errors import ChannelError
from justkernel.shared.ids import AgentId


# ---- static channels --------------------------------------------------------
def test_static_channels_and_names() -> None:
    assert Channel.mentor_board().name == "mentor_board"
    assert Channel.consultant_board().name == "consultant_board"
    assert Channel.hardware().name == "hardware"
    assert Channel.control().name == "control"


def test_worker_channel_round_trip() -> None:
    mentor = AgentId.generate()
    worker = AgentId.generate()
    channel = Channel.worker(mentor, worker)

    assert channel.kind is ChannelKind.WORKER
    assert channel.name == f"worker:{mentor}:{worker}"
    assert Channel.parse(channel.name) == channel


# ---- validation -------------------------------------------------------------
def test_worker_channel_requires_both_ids() -> None:
    with pytest.raises(ChannelError):
        Channel(ChannelKind.WORKER)
    with pytest.raises(ChannelError):
        Channel(ChannelKind.WORKER, mentor_id=AgentId.generate())


def test_non_worker_channel_rejects_ids() -> None:
    with pytest.raises(ChannelError):
        Channel(ChannelKind.MENTOR_BOARD, mentor_id=AgentId.generate())


def test_invalid_channel_names() -> None:
    for name in ("", "mentor-board", "worker:", "worker:bad:worker", "unknown"):
        with pytest.raises(ChannelError):
            Channel.parse(name)

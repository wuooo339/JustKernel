from __future__ import annotations

import pytest

from justkernel.cluster.direction import Direction
from justkernel.cluster.errors import DirectionError
from justkernel.cluster.state import DirectionState
from justkernel.shared.ids import AgentId, ClusterId, DirectionId


# ---- helpers ----------------------------------------------------------------
def _direction(**overrides: object) -> Direction:
    values: dict[str, object] = {
        "id": DirectionId.generate(),
        "cluster_id": ClusterId.generate(),
        "mentor_id": AgentId.generate(),
        "objective": "improve memory access",
        "constraints": ("budget",),
        "created_at": 0,
    }
    values.update(overrides)
    return Direction(**values)


# ---- lifecycle --------------------------------------------------------------
def test_direction_lifecycle_to_completed() -> None:
    direction = _direction()

    assert direction.state is DirectionState.PROPOSED
    direction.activate()
    assert direction.state is DirectionState.ACTIVE

    direction.pause()
    assert direction.state is DirectionState.PAUSED

    direction.resume()
    assert direction.state is DirectionState.ACTIVE

    direction.set_summary("candidate improved")
    direction.complete("goal reached", 100)

    assert direction.state is DirectionState.COMPLETED
    assert direction.summary == "candidate improved"
    assert direction.close_reason == "goal reached"
    assert direction.closed_at == 100


def test_direction_can_be_abandoned() -> None:
    direction = _direction()
    direction.abandon("no gain", 200)

    assert direction.state is DirectionState.ABANDONED
    assert direction.close_reason == "no gain"
    assert direction.closed_at == 200


# ---- invalid transitions ----------------------------------------------------
def test_invalid_direction_transitions() -> None:
    direction = _direction()

    with pytest.raises(DirectionError):
        direction.pause()
    with pytest.raises(DirectionError):
        direction.resume()
    with pytest.raises(DirectionError):
        direction.complete("done", 100)

    direction.activate()
    with pytest.raises(DirectionError):
        direction.activate()
    with pytest.raises(DirectionError):
        direction.resume()
    with pytest.raises(DirectionError):
        direction.complete("", 100)


def test_terminal_direction_rejects_further_changes() -> None:
    direction = _direction()
    direction.activate()
    direction.complete("done", 100)

    with pytest.raises(DirectionError):
        direction.set_summary("late")
    with pytest.raises(DirectionError):
        direction.abandon("late", 200)

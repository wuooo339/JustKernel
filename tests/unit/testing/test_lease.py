from __future__ import annotations

import pytest

from justkernel.shared.ids import AgentId, LeaseId, TaskId
from justkernel.testing.errors import LeaseError
from justkernel.testing.lease import DeviceId, HardwareLease
from justkernel.testing.state import LeaseState


# ---- helpers ----------------------------------------------------------------
def _lease(**overrides: object) -> HardwareLease:
    values: dict[str, object] = {
        "id": LeaseId.generate(),
        "device_id": DeviceId("npu:0"),
        "task_id": TaskId.generate(),
        "owner_agent_id": AgentId.generate(),
    }
    values.update(overrides)
    return HardwareLease(**values)


# ---- lifecycle --------------------------------------------------------------
def test_lease_lifecycle_acquire_and_release() -> None:
    lease = _lease()

    assert lease.state is LeaseState.QUEUED
    lease.acquire(100, 50)
    assert lease.state is LeaseState.LEASED
    assert lease.acquired_at == 100
    assert lease.expires_at == 150

    lease.release(120)
    assert lease.state is LeaseState.RELEASED
    assert lease.released_at == 120


def test_lease_can_expire() -> None:
    lease = _lease()
    lease.acquire(100, 50)
    lease.expire(150)

    assert lease.state is LeaseState.EXPIRED


# ---- guards -----------------------------------------------------------------
def test_invalid_lease_transitions() -> None:
    lease = _lease()

    with pytest.raises(LeaseError):
        lease.release(100)
    with pytest.raises(LeaseError):
        lease.expire(100)
    with pytest.raises(LeaseError):
        lease.acquire(100, 0)

    lease.acquire(100, 50)
    with pytest.raises(LeaseError):
        lease.acquire(110, 50)
    with pytest.raises(LeaseError):
        lease.release(99)
    with pytest.raises(LeaseError):
        lease.expire(149)

    lease.release(120)
    with pytest.raises(LeaseError):
        lease.acquire(130, 10)
    with pytest.raises(LeaseError):
        lease.expire(200)


def test_lease_state_fields_are_consistent() -> None:
    with pytest.raises(LeaseError):
        _lease(state=LeaseState.LEASED)
    with pytest.raises(LeaseError):
        _lease(state=LeaseState.RELEASED)
    with pytest.raises(LeaseError):
        _lease(state=LeaseState.QUEUED, acquired_at=10)


def test_device_id_must_be_non_empty() -> None:
    with pytest.raises(LeaseError):
        DeviceId("")

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from justkernel.shared.events import DomainEvent, EventError, EventType
from justkernel.shared.ids import ClusterId, EventId
from justkernel.shared.principal import Principal


# ---- helpers ----------------------------------------------------------------
def _event(**overrides: object) -> DomainEvent:
    values: dict[str, object] = {
        "id": EventId.generate(),
        "cluster_id": ClusterId.generate(),
        "type": EventType.CLUSTER_STARTED,
        "event_version": 1,
        "aggregate_type": "Cluster",
        "aggregate_id": "cluster-1",
        "aggregate_version": 0,
        "actor": Principal.system(),
        "occurred_at": 0,
        "payload": {"state": "RUNNING"},
    }
    values.update(overrides)
    return DomainEvent(**values)


# ---- envelope ---------------------------------------------------------------
def test_event_type_values_and_payload_immutability() -> None:
    event = _event()

    assert EventType.CLUSTER_STARTED == "cluster.started"

    with pytest.raises(TypeError):
        event.payload["state"] = "STOPPED"


def test_event_is_frozen() -> None:
    event = _event()

    with pytest.raises(FrozenInstanceError):
        event.event_version = 2


def test_event_metadata_is_validated() -> None:
    with pytest.raises(EventError):
        _event(event_version=0)
    with pytest.raises(EventError):
        _event(aggregate_version=-1)
    with pytest.raises(EventError):
        _event(occurred_at=-1)
    with pytest.raises(EventError):
        _event(aggregate_type="")
    with pytest.raises(EventError):
        _event(aggregate_id="")
    with pytest.raises(EventError):
        _event(correlation_id="")

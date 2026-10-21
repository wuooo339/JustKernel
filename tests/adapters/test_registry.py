from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from justkernel.platform.persistence.database import connect
from justkernel.platform.persistence.registry import (
    OperatorActiveError,
    OperatorRegistry,
    RegistryError,
    apply_registry_schema,
)


# ---- helpers ----------------------------------------------------------------
def _registry(tmp_path: Path) -> tuple[sqlite3.Connection, OperatorRegistry]:
    connection = connect(str(tmp_path / "registry.db"))
    apply_registry_schema(connection)
    return connection, OperatorRegistry(connection)


def _reserve(
    registry: OperatorRegistry,
    *,
    operator_id: str = "op-1",
    cluster_id: str = "cluster-1",
    reservation_key: str = "reservation-1",
    now_ms: int = 0,
) -> object:
    return registry.reserve(
        operator_id=operator_id,
        cluster_id=cluster_id,
        journal_ref=f"clusters/{cluster_id}/journal.db",
        reservation_key=reservation_key,
        now_ms=now_ms,
    )


# ---- reservation ------------------------------------------------------------
def test_reserve_and_read(tmp_path: Path) -> None:
    _, registry = _registry(tmp_path)
    entry = _reserve(registry)

    assert entry.operator_id == "op-1"
    assert entry.state == "INITIALIZING"
    assert registry.get("cluster-1") == entry
    assert registry.get_active("op-1") == entry
    assert registry.list_active() == (entry,)


def test_second_active_cluster_is_rejected(tmp_path: Path) -> None:
    _, registry = _registry(tmp_path)
    _reserve(registry)

    with pytest.raises(OperatorActiveError) as error:
        _reserve(registry, cluster_id="cluster-2", reservation_key="reservation-2")

    assert error.value.code == "registry.operator_active"
    assert registry.get_active("op-1").cluster_id == "cluster-1"


def test_release_is_idempotent_and_allows_new_cluster(tmp_path: Path) -> None:
    _, registry = _registry(tmp_path)
    _reserve(registry)

    assert registry.release("cluster-1", "STOPPED") is True
    assert registry.get_active("op-1") is None
    assert registry.release("cluster-1", "STOPPED") is False
    assert registry.release("missing", "STOPPED") is False

    entry = _reserve(registry, cluster_id="cluster-2", reservation_key="reservation-2")
    assert registry.get_active("op-1") == entry


def test_release_requires_terminal_state(tmp_path: Path) -> None:
    _, registry = _registry(tmp_path)
    _reserve(registry)

    with pytest.raises(RegistryError):
        registry.release("cluster-1", "RUNNING")


# ---- reservation idempotency ------------------------------------------------
def test_same_reservation_key_is_idempotent(tmp_path: Path) -> None:
    connection, registry = _registry(tmp_path)
    first = _reserve(registry)
    second = _reserve(registry)

    assert second == first
    assert connection.execute("SELECT COUNT(*) FROM cluster_registry").fetchone()[0] == 1


def test_conflicting_reservation_key_is_rejected(tmp_path: Path) -> None:
    connection, registry = _registry(tmp_path)
    _reserve(registry)

    with pytest.raises(RegistryError):
        _reserve(
            registry,
            operator_id="op-2",
            cluster_id="cluster-2",
            reservation_key="reservation-1",
        )

    assert connection.execute("SELECT COUNT(*) FROM cluster_registry").fetchone()[0] == 1


# ---- cross-connection and schema --------------------------------------------
def test_two_connections_cannot_activate_the_same_operator(tmp_path: Path) -> None:
    connection_a, registry_a = _registry(tmp_path)
    connection_b = connect(str(tmp_path / "registry.db"))
    registry_b = OperatorRegistry(connection_b)

    _reserve(registry_a)

    with pytest.raises(OperatorActiveError):
        _reserve(registry_b, cluster_id="cluster-2", reservation_key="reservation-2")

    assert registry_b.get_active("op-1").cluster_id == "cluster-1"
    connection_a.close()
    connection_b.close()


def test_registry_schema_is_idempotent(tmp_path: Path) -> None:
    connection = connect(str(tmp_path / "registry.db"))
    apply_registry_schema(connection)
    apply_registry_schema(connection)

    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert "cluster_registry" in tables

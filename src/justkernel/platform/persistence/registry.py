"""Global operator registry."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError

TERMINAL_STATES = frozenset({"COMPLETED", "STOPPED", "FAILED"})

REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS cluster_registry (
  cluster_id TEXT PRIMARY KEY,
  operator_id TEXT NOT NULL,
  journal_ref TEXT NOT NULL,
  state TEXT NOT NULL,
  reservation_key TEXT NOT NULL UNIQUE,
  created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_cluster_per_operator
  ON cluster_registry(operator_id)
  WHERE state NOT IN ('COMPLETED','STOPPED','FAILED');
"""


# ---- errors -----------------------------------------------------------------
class RegistryError(JustKernelError):
    code = ErrorCode.REGISTRY_CONFLICT


class OperatorActiveError(RegistryError):
    code = ErrorCode.REGISTRY_OPERATOR_ACTIVE


# ---- RegistryEntry ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RegistryEntry:
    cluster_id: str
    operator_id: str
    journal_ref: str
    state: str
    reservation_key: str
    created_at: int


# ---- apply_registry_schema --------------------------------------------------
def apply_registry_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(REGISTRY_SCHEMA)


# ---- OperatorRegistry -------------------------------------------------------
class OperatorRegistry:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def reserve(
        self,
        *,
        operator_id: str,
        cluster_id: str,
        journal_ref: str,
        reservation_key: str,
        now_ms: int,
        state: str = "INITIALIZING",
    ) -> RegistryEntry:
        self._validate(operator_id, cluster_id, journal_ref, reservation_key, now_ms, state)
        existing = self.get(cluster_id)
        if existing is not None:
            if existing.reservation_key == reservation_key:
                return existing
            raise RegistryError(f"cluster already registered: {cluster_id}")
        self._insert(operator_id, cluster_id, journal_ref, state, reservation_key, now_ms)
        return RegistryEntry(
            cluster_id=cluster_id,
            operator_id=operator_id,
            journal_ref=journal_ref,
            state=state,
            reservation_key=reservation_key,
            created_at=now_ms,
        )

    def _insert(
        self,
        operator_id: str,
        cluster_id: str,
        journal_ref: str,
        state: str,
        reservation_key: str,
        now_ms: int,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO cluster_registry (
                    cluster_id, operator_id, journal_ref, state,
                    reservation_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cluster_id, operator_id, journal_ref, state, reservation_key, now_ms),
            )
        except sqlite3.IntegrityError as error:
            active = self.get_active(operator_id)
            if active is not None:
                raise OperatorActiveError(
                    f"operator already has active cluster: {operator_id}"
                ) from error
            raise RegistryError("reservation key already exists") from error

    def get(self, cluster_id: str) -> RegistryEntry | None:
        row = self.connection.execute(
            "SELECT * FROM cluster_registry WHERE cluster_id = ?", (cluster_id,)
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_active(self, operator_id: str) -> RegistryEntry | None:
        row = self.connection.execute(
            """
            SELECT * FROM cluster_registry
            WHERE operator_id = ? AND state NOT IN ('COMPLETED','STOPPED','FAILED')
            """,
            (operator_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_active(self) -> tuple[RegistryEntry, ...]:
        rows = self.connection.execute(
            """
            SELECT * FROM cluster_registry
            WHERE state NOT IN ('COMPLETED','STOPPED','FAILED')
            ORDER BY created_at, cluster_id
            """
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def release(self, cluster_id: str, state: str) -> bool:
        if state not in TERMINAL_STATES:
            raise RegistryError(f"release state must be terminal: {state}")
        cursor = self.connection.execute(
            """
            UPDATE cluster_registry SET state = ?
            WHERE cluster_id = ? AND state NOT IN ('COMPLETED','STOPPED','FAILED')
            """,
            (state, cluster_id),
        )
        return cursor.rowcount == 1

    def _validate(
        self,
        operator_id: str,
        cluster_id: str,
        journal_ref: str,
        reservation_key: str,
        now_ms: int,
        state: str,
    ) -> None:
        if not operator_id or not cluster_id or not journal_ref or not reservation_key:
            raise RegistryError("reservation fields must be non-empty")
        if now_ms < 0:
            raise RegistryError("created_at must be non-negative")
        if state in TERMINAL_STATES:
            raise RegistryError("new reservation cannot be terminal")

    def _from_row(self, row: sqlite3.Row) -> RegistryEntry:
        return RegistryEntry(
            cluster_id=row["cluster_id"],
            operator_id=row["operator_id"],
            journal_ref=row["journal_ref"],
            state=row["state"],
            reservation_key=row["reservation_key"],
            created_at=row["created_at"],
        )

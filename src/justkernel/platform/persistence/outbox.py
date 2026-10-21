"""Idempotent outbox repository."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from justkernel.shared.ids import ClusterId
from justkernel.shared.json import canonical_json


# ---- OutboxEntry ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class OutboxEntry:
    id: str
    cluster_id: ClusterId
    kind: str
    payload: Mapping[str, object]
    idempotency_key: str
    available_at: int
    attempts: int = 0

    def __post_init__(self) -> None:
        if not self.id or not self.kind or not self.idempotency_key:
            raise ValueError("outbox id/kind/idempotency_key must be non-empty")
        if self.available_at < 0 or self.attempts < 0:
            raise ValueError("outbox time/attempts must be non-negative")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


# ---- OutboxRepository -------------------------------------------------------
class OutboxRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def enqueue(self, entry: OutboxEntry) -> bool:
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO outbox (
                id, cluster_id, kind, payload_json, idempotency_key,
                available_at, attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.cluster_id.value,
                entry.kind,
                canonical_json(dict(entry.payload)),
                entry.idempotency_key,
                entry.available_at,
                entry.attempts,
            ),
        )
        return cursor.rowcount == 1

    def pending(self, now_ms: int, limit: int = 100) -> tuple[OutboxEntry, ...]:
        rows = self.connection.execute(
            """
            SELECT * FROM outbox
            WHERE available_at <= ?
            ORDER BY available_at, id
            LIMIT ?
            """,
            (now_ms, limit),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def mark_attempt(self, outbox_id: str) -> None:
        cursor = self.connection.execute(
            "UPDATE outbox SET attempts = attempts + 1 WHERE id = ?",
            (outbox_id,),
        )
        if cursor.rowcount != 1:
            raise KeyError(outbox_id)

    def _from_row(self, row: sqlite3.Row) -> OutboxEntry:
        return OutboxEntry(
            id=row["id"],
            cluster_id=ClusterId(row["cluster_id"]),
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            idempotency_key=row["idempotency_key"],
            available_at=row["available_at"],
            attempts=row["attempts"],
        )

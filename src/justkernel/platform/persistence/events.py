"""Append-only event store."""

from __future__ import annotations

import json
import sqlite3

from justkernel.shared.events import DomainEvent, EventError, EventType
from justkernel.shared.ids import ClusterId, EventId
from justkernel.shared.json import canonical_json
from justkernel.shared.principal import Principal


# ---- EventStore -------------------------------------------------------------
class EventStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def append(self, event: DomainEvent) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO events (
                    event_id, cluster_id, type, event_version, aggregate_type,
                    aggregate_id, aggregate_version, actor, correlation_id,
                    causation_id, payload_json, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id.value,
                    event.cluster_id.value,
                    event.type.value,
                    event.event_version,
                    event.aggregate_type,
                    event.aggregate_id,
                    event.aggregate_version,
                    str(event.actor),
                    event.correlation_id,
                    event.causation_id,
                    canonical_json(dict(event.payload)),
                    event.occurred_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise EventError(f"event already exists: {event.id}") from error

    def read_after(self, seq: int = 0, limit: int = 100) -> tuple[DomainEvent, ...]:
        return tuple(event for _, event in self.read_after_with_seq(seq, limit))

    def read_after_with_seq(
        self, seq: int = 0, limit: int = 100
    ) -> tuple[tuple[int, DomainEvent], ...]:
        rows = self.connection.execute(
            "SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?",
            (seq, limit),
        ).fetchall()
        return tuple((int(row["seq"]), self._from_row(row)) for row in rows)

    def _from_row(self, row: sqlite3.Row) -> DomainEvent:
        return DomainEvent(
            id=EventId(row["event_id"]),
            cluster_id=ClusterId(row["cluster_id"]),
            type=EventType(row["type"]),
            event_version=row["event_version"],
            aggregate_type=row["aggregate_type"],
            aggregate_id=row["aggregate_id"],
            aggregate_version=row["aggregate_version"],
            actor=Principal.parse(row["actor"]),
            occurred_at=row["occurred_at"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            payload=json.loads(row["payload_json"]),
        )

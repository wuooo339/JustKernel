"""Explicit SQLite UnitOfWork."""

from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Self

from justkernel.platform.persistence.events import EventStore
from justkernel.platform.persistence.outbox import OutboxRepository
from justkernel.platform.persistence.repositories import AgentRepository, ClusterRepository


# ---- UnitOfWork -------------------------------------------------------------
class UnitOfWork:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.clusters = ClusterRepository(connection)
        self.agents = AgentRepository(connection)
        self.events = EventStore(connection)
        self.outbox = OutboxRepository(connection)

    def __enter__(self) -> Self:
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.connection.execute("COMMIT")
        else:
            self.connection.execute("ROLLBACK")

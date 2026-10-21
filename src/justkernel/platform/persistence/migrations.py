"""Ordered SQLite journal migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from time import time_ns

from justkernel.platform.persistence.schema import INITIAL_SCHEMA, LEGACY_SCHEMA


# ---- Migration --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    sql: str


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, sql=INITIAL_SCHEMA),
    Migration(version=2, sql=LEGACY_SCHEMA),
)


# ---- apply_migrations -------------------------------------------------------
def apply_migrations(connection: sqlite3.Connection) -> int:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
        """
    )
    applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
    count = 0
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        connection.executescript(migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (migration.version, time_ns() // 1_000_000),
        )
        connection.commit()
        count += 1
    return count

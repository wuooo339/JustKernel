"""SQLite connection helper."""

from __future__ import annotations

import sqlite3


# ---- connect ----------------------------------------------------------------
def connect(path: str = ":memory:", *, foreign_keys: bool = True) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection

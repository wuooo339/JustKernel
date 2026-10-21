"""Read-only import of legacy lab data into LEGACY records."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import time_ns
from uuid import uuid4

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.json import canonical_json


# ---- errors -----------------------------------------------------------------
class LegacyImportError(JustKernelError):
    code = ErrorCode.MIGRATION_ERROR


# ---- report -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LegacyImportReport:
    import_id: str
    source_path: str
    source_digest: str
    records_imported: int
    already_imported: bool


# ---- LegacyImporter ---------------------------------------------------------
class LegacyImporter:
    LEGACY_TABLES = ("teams", "members", "runs", "experiences", "events")

    def __init__(self, connection: sqlite3.Connection, old_path: Path) -> None:
        self.connection = connection
        self.old_path = old_path

    def import_data(self, *, now_ms: int | None = None) -> LegacyImportReport:
        if not self.old_path.is_file():
            raise LegacyImportError(f"legacy database not found: {self.old_path}")
        if now_ms is None:
            now_ms = time_ns() // 1_000_000
        source_path = str(self.old_path.resolve())
        source_digest = sha256(self.old_path.read_bytes()).hexdigest()
        existing = self._existing(source_path, source_digest)
        if existing is not None:
            return existing
        records = self._read_old()
        import_id = uuid4().hex
        self._store(import_id, source_path, source_digest, now_ms, records)
        return LegacyImportReport(import_id, source_path, source_digest, len(records), False)

    def _store(
        self,
        import_id: str,
        source_path: str,
        source_digest: str,
        now_ms: int,
        records: list[tuple[str, str, dict[str, object]]],
    ) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """
                INSERT INTO legacy_imports
                (id, source_path, source_digest, imported_at, record_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (import_id, source_path, source_digest, now_ms, len(records)),
            )
            for kind, legacy_id, payload in records:
                self.connection.execute(
                    """
                    INSERT INTO legacy_records
                    (id, import_id, kind, legacy_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"legacy-{import_id}-{kind}-{legacy_id}",
                        import_id,
                        kind,
                        legacy_id,
                        canonical_json(payload),
                        now_ms,
                    ),
                )
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def _existing(self, source_path: str, source_digest: str) -> LegacyImportReport | None:
        row = self.connection.execute(
            """
            SELECT id, source_path, source_digest, record_count
            FROM legacy_imports WHERE source_path = ? AND source_digest = ?
            """,
            (source_path, source_digest),
        ).fetchone()
        if row is None:
            return None
        return LegacyImportReport(
            row["id"], row["source_path"], row["source_digest"], row["record_count"], True
        )

    def _read_old(self) -> list[tuple[str, str, dict[str, object]]]:
        old = sqlite3.connect(f"file:{self.old_path.resolve()}?mode=ro", uri=True)
        old.row_factory = sqlite3.Row
        try:
            old.execute("PRAGMA query_only = ON")
            tables = {
                row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            records: list[tuple[str, str, dict[str, object]]] = []
            for table in self.LEGACY_TABLES:
                if table not in tables:
                    continue
                for row in old.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                    data = dict(row)
                    legacy_id = str(data.get("id") or f"{table}-{len(records)}")
                    records.append((table.upper(), legacy_id, _json_safe(data)))
            return records
        finally:
            old.close()


def _json_safe(value: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str) and key in {"data", "payload", "trace_url"}:
            try:
                result[key] = json.loads(item)
            except json.JSONDecodeError:
                result[key] = item
        else:
            result[key] = item
    return result

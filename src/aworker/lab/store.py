"""Durable experiment journal and transactional physical-device leases."""

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from aworker.lab.domain import StageUpdate


# ---- identifier -------------------------------------------------------------
def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("invalid identifier")
    return value


# ---- LabStore ---------------------------------------------------------------
class LabStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    team TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, host TEXT NOT NULL, device INTEGER NOT NULL,
                    UNIQUE(host, device));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, team TEXT NOT NULL, state TEXT NOT NULL,
                    device TEXT, token TEXT, created REAL NOT NULL, error TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS exclusive_device ON jobs(device)
                    WHERE state = 'running';
                CREATE TABLE IF NOT EXISTS teams (
                    id TEXT PRIMARY KEY, runtime TEXT NOT NULL, model TEXT,
                    session TEXT, active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, team TEXT NOT NULL, kind TEXT NOT NULL,
                    state TEXT NOT NULL, created REAL NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS members (
                    team TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
                    model TEXT, PRIMARY KEY(team,name));
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, team TEXT NOT NULL, model TEXT NOT NULL,
                    state TEXT NOT NULL, thread_id TEXT NOT NULL,
                    started REAL NOT NULL, ended REAL, error TEXT, trace_url TEXT);
                CREATE TABLE IF NOT EXISTS experiences (
                    id TEXT PRIMARY KEY, team TEXT NOT NULL, created REAL NOT NULL,
                    data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inbox (
                    id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
                    created REAL NOT NULL, message TEXT NOT NULL, artifact TEXT);
            """)

    # ---- connections --------------------------------------------------------
    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        # Dashboard context grouping must also work when the OS temp folder is unavailable.
        db.execute("PRAGMA temp_store=MEMORY")
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---- events -------------------------------------------------------------
    def event(self, team_id: str, kind: str, **data) -> int:
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO events(at,team,kind,data) VALUES(?,?,?,?)",
                (time.time(), team_id, kind, json.dumps(data, ensure_ascii=False)),
            )
            return cursor.lastrowid

    def events(self, after: int = 0, limit: int = 500) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?",
                (after, min(max(limit, 1), 2000)),
            ).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    # ---- bounded live bootstrap; complete history remains in the journal ----
    def dashboard_events(self, limit: int = 1500) -> dict:
        with self.connection() as db:
            cursor = db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM events WHERE seq<=?", (cursor,)).fetchone()[0]
            recent = db.execute(
                "SELECT * FROM events WHERE seq<=? ORDER BY seq DESC LIMIT ?",
                (cursor, min(max(limit, 1), 3000)),
            ).fetchall()
            # Preserve old official outcomes, each team's stage and current model context.
            context = db.execute(
                """SELECT * FROM events WHERE seq IN (
                    SELECT MAX(seq) FROM events WHERE seq<=? AND kind IN (
                        'stage.updated','judge.submission.updated','control.started',
                        'control.completed','control.failed','control.cancelled',
                        'team.turn.started','team.turn.completed','team.turn.failed',
                        'model.started','model.completed','agent.message','workspace.changed',
                        'tool.started','tool.completed','model.slot.acquired','model.slot.waiting'
                    ) GROUP BY team,kind,CASE
                        WHEN kind='stage.updated' THEN json_extract(data,'$.stage')
                        WHEN kind='judge.submission.updated' THEN
                            COALESCE(json_extract(data,'$.problem_id'),'') || ':' ||
                            COALESCE(json_extract(data,'$.submission_id'),seq)
                        ELSE '' END
                )""",
                (cursor,),
            ).fetchall()
            messages = db.execute(
                "SELECT * FROM events WHERE seq<=? AND kind='team.message' "
                "ORDER BY seq DESC LIMIT 500",
                (cursor,),
            ).fetchall()
        selected = {r["seq"]: r for r in [*recent, *context, *messages]}
        return {
            "cursor": cursor,
            "total": total,
            "events": [
                {**dict(selected[key]), "data": json.loads(selected[key]["data"])}
                for key in sorted(selected)
            ],
        }

    def stage(self, team: str, update: StageUpdate) -> None:
        self.event(team, "stage.updated", **update.model_dump(mode="json"))

    # ---- device scheduling --------------------------------------------------
    def register_device(self, name: str, host: str, device: int) -> None:
        identifier(name)
        with self.connection() as db:
            existing = db.execute("SELECT * FROM devices WHERE id=?", (name,)).fetchone()
            if existing and (existing["host"], existing["device"]) != (host, device):
                raise ValueError("device identity is immutable")
            duplicate = db.execute(
                "SELECT id FROM devices WHERE host=? AND device=?", (host, device)
            ).fetchone()
            if duplicate and duplicate["id"] != name:
                raise ValueError("physical device already registered")
            db.execute("INSERT OR IGNORE INTO devices VALUES(?,?,?)", (name, host, device))

    def enqueue(self, team: str) -> str:
        job = uuid4().hex
        with self.connection() as db:
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,NULL,NULL,?,NULL)",
                (job, identifier(team), "queued", time.time()),
            )
        self.event(team, "device.queued", job_id=job)
        return job

    def claim(self, job: str, max_active: int = 8) -> dict | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if not row or row["state"] != "queued":
                raise ValueError("job is not queued")
            first = db.execute(
                """SELECT id FROM jobs WHERE state='queued' AND team NOT IN
                (SELECT team FROM jobs WHERE state='running') ORDER BY created,id LIMIT 1"""
            ).fetchone()
            count = db.execute("SELECT count(*) FROM jobs WHERE state='running'").fetchone()[0]
            if first is None or first[0] != job or count >= max_active:
                return None
            # A team can hold only one physical device at a time.
            if db.execute(
                "SELECT 1 FROM jobs WHERE team=? AND state='running'", (row["team"],)
            ).fetchone():
                return None
            device = db.execute("""SELECT * FROM devices WHERE id NOT IN
                (SELECT device FROM jobs WHERE state='running') ORDER BY id LIMIT 1""").fetchone()
            if not device:
                return None
            token = uuid4().hex
            db.execute(
                "UPDATE jobs SET state='running',device=?,token=? WHERE id=?",
                (device["id"], token, job),
            )
            return {**dict(device), "token": token}

    def finish(self, job: str, token: str, error: str | None = None) -> None:
        with self.connection() as db:
            changed = db.execute(
                "UPDATE jobs SET state=?,error=? WHERE id=? AND token=? AND state='running'",
                ("failed" if error else "completed", error, job, token),
            ).rowcount
            if changed != 1:
                raise ValueError("stale or foreign device lease")

    def cancel_queued(self, job: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state='queued'", (job,))

    # ---- team membership ----------------------------------------------------
    def join(self, team: str, runtime: str, model: str | None) -> None:
        identifier(team)
        if runtime != "deepagents":
            raise ValueError("teams must use the unified deepagents harness")
        with self.connection() as db:
            previous = db.execute("SELECT * FROM teams WHERE id=?", (team,)).fetchone()
            if previous and (previous["runtime"], previous["model"]) != (runtime, model):
                raise ValueError("use a new team ID when changing model profile")
            db.execute(
                """INSERT INTO teams(id,runtime,model) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET active=1""",
                (team, runtime, model),
            )
        self.event(team, "team.joined", runtime=runtime, model=model)

    # ---- explicit provider migration preserves code and historical runs -------
    def rebind_model(self, team: str, model: str) -> None:
        identifier(team)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM teams WHERE id=?", (team,)).fetchone()
            if not previous or not previous["active"]:
                raise ValueError("select an active team")
            if db.execute(
                "SELECT 1 FROM operations WHERE team=? AND state='running'", (team,)
            ).fetchone():
                raise ValueError("finish or cancel the active task before switching models")
            if previous["model"] == model:
                return
            session = "deepagents-" + team + "-" + uuid4().hex[:12]
            db.execute("UPDATE teams SET model=?,session=? WHERE id=?", (model, session, team))
            db.execute("UPDATE members SET model=NULL WHERE team=?", (team,))
            db.execute(
                "INSERT INTO events(at,team,kind,data) VALUES(?,?,?,?)",
                (
                    time.time(),
                    team,
                    "team.model.changed",
                    json.dumps(
                        {
                            "old_model": previous["model"],
                            "model": model,
                            "previous_session": previous["session"],
                            "session": session,
                        }
                    ),
                ),
            )

    def allocate_teams(
        self, profiles: list[tuple[str, str]], count: int, max_active: int
    ) -> list[tuple[str, str]]:
        if not profiles or not 1 <= count <= max_active:
            raise ValueError("select configured models and a valid team count")
        allocated = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            teams = db.execute("SELECT id,model,active FROM teams").fetchall()
            if sum(bool(t["active"]) for t in teams) + count > max_active:
                raise ValueError("team capacity reached")
            used = {t["id"] for t in teams}
            loads = {
                key: sum(t["active"] and t["model"] == key for t in teams) for key, _ in profiles
            }
            for _ in range(count):
                model, prefix = min(profiles, key=lambda p: loads[p[0]])
                identifier(prefix)
                serial = 1
                while (name := f"{prefix}-{serial:03d}") in used:
                    serial += 1
                db.execute(
                    "INSERT INTO teams(id,runtime,model,active) VALUES(?,'deepagents',?,1)",
                    (name, model),
                )
                used.add(name)
                loads[model] += 1
                allocated.append((name, model))
        return allocated

    def session(self, team: str, session: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE teams SET session=? WHERE id=?", (session, team))

    def leave(self, team: str) -> None:
        with self.connection() as db:
            if db.execute(
                "SELECT 1 FROM jobs WHERE team=? AND state IN ('queued','running')", (team,)
            ).fetchone():
                raise ValueError("finish or cancel device jobs before leaving")
            db.execute("UPDATE teams SET active=0 WHERE id=?", (team,))
        self.event(team, "team.left")

    def snapshot(self, history_limit: int | None = None) -> dict:
        with self.connection() as db:
            data = {}
            for name in ("devices", "jobs", "teams", "operations", "members", "runs"):
                query, args = f"SELECT * FROM {name}", ()
                if history_limit is not None and name in {"jobs", "operations", "runs"}:
                    # Keep live operations and each team's latest record beyond the window.
                    query += (
                        f" WHERE state IN ('running','queued') OR rowid IN "
                        f"(SELECT MAX(rowid) FROM {name} GROUP BY team) OR rowid IN "
                        f"(SELECT rowid FROM {name} ORDER BY rowid DESC LIMIT ?)"
                    )
                    args = (max(1, history_limit),)
                data[name] = [dict(r) for r in db.execute(query, args)]
            return data

    # ---- specialists, conversations and verified experience -----------------
    def set_members(self, team: str, members: list[dict]) -> None:
        with self.connection() as db:
            if db.execute(
                "SELECT 1 FROM operations WHERE team=? AND state='running'", (team,)
            ).fetchone():
                raise ValueError("finish the active team task before editing its roster")
            db.execute("DELETE FROM members WHERE team=?", (team,))
            db.executemany(
                "INSERT INTO members(team,name,role,model) VALUES(?,?,?,?)",
                [(team, item["name"], item["role"], item.get("model")) for item in members],
            )
        self.event(team, "team.roster.updated", members=members)

    def message(
        self,
        sender: str,
        recipient: str,
        message: str,
        artifact: str | None,
        delivery_id: str | None = None,
        transport: str = "local",
        topic: str | None = None,
    ) -> str:
        key = identifier(delivery_id) if delivery_id else uuid4().hex
        with self.connection() as db:
            changed = db.execute(
                "INSERT OR IGNORE INTO inbox VALUES(?,?,?,?,?,?)",
                (key, sender, recipient, time.time(), message, artifact),
            ).rowcount
        if changed:
            self.event(
                sender,
                "team.message",
                recipient=recipient,
                message=message,
                artifact=artifact,
                message_id=key,
                transport=transport,
                topic=topic,
            )
        return key

    def messages(self, team: str) -> list[dict]:
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM inbox WHERE recipient=? ORDER BY created DESC LIMIT 50", (team,)
                )
            ]

    def experience(self, team: str, data: dict) -> str:
        key = uuid4().hex
        with self.connection() as db:
            db.execute(
                "INSERT INTO experiences VALUES(?,?,?,?)",
                (key, team, time.time(), json.dumps(data, ensure_ascii=False)),
            )
        self.event(team, "skill.created", skill_id=key, **data)
        return key

    def experiences(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM experiences ORDER BY created DESC").fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def run_started(self, run: str, team: str, model: str, thread: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,'running',?,?,NULL,NULL,NULL)",
                (run, team, model, thread, time.time()),
            )

    def run_finished(
        self, run: str, state: str, error: str | None = None, trace_url: str | None = None
    ) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE runs SET state=?,ended=?,error=?,trace_url=? WHERE id=?",
                (state, time.time(), error, trace_url, run),
            )

    # ---- control operations -------------------------------------------------
    def operation(self, operation_id: str, team: str, kind: str) -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM operations WHERE team=? AND state='running'", (team,)
            ).fetchone():
                raise ValueError("team already has an active operation")
            db.execute(
                "INSERT INTO operations VALUES(?,?,?,'running',?,NULL)",
                (operation_id, team, kind, time.time()),
            )

    def operation_finished(self, operation_id: str, state: str, error: str | None = None):
        with self.connection() as db:
            db.execute(
                "UPDATE operations SET state=?,error=? WHERE id=?", (state, error, operation_id)
            )

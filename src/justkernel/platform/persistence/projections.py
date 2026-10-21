"""Event-sourced read models and replay runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from time import time_ns
from typing import Protocol

from justkernel.platform.persistence.events import EventStore
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError
from justkernel.shared.events import DomainEvent, EventType
from justkernel.shared.ids import AgentId, CandidateId, ClusterId, DirectionId


# ---- ProjectionError --------------------------------------------------------
class ProjectionError(JustKernelError):
    code = ErrorCode.PROJECTION_INVALID


# ---- helpers ----------------------------------------------------------------
def _text(event: DomainEvent, key: str) -> str:
    value = event.payload.get(key)
    if not isinstance(value, str) or not value:
        raise ProjectionError(f"{event.type} payload requires {key}")
    return value


def _optional_text(event: DomainEvent, key: str) -> str | None:
    value = event.payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProjectionError(f"{event.type} payload has invalid {key}")
    return value


def _agent(event: DomainEvent, key: str) -> AgentId:
    try:
        return AgentId(_text(event, key))
    except Exception as error:
        raise ProjectionError(f"{event.type} payload has invalid {key}") from error


# ---- MentorBoardProjection -------------------------------------------------
@dataclass(frozen=True, slots=True)
class BoardPost:
    post_id: str
    board: str
    topic: str
    author_agent_id: AgentId
    payload: dict[str, object]
    occurred_at: int


class MentorBoardProjection:
    name = "mentor_board"

    def __init__(self) -> None:
        self.posts: list[BoardPost] = []

    def reset(self) -> None:
        self.posts.clear()

    def apply(self, event: DomainEvent) -> None:
        if event.type is not EventType.BOARD_POSTED:
            return
        payload = event.payload.get("payload")
        if not isinstance(payload, dict):
            raise ProjectionError("board post payload must be an object")
        self.posts.append(
            BoardPost(
                post_id=_text(event, "post_id"),
                board=_text(event, "board"),
                topic=_text(event, "topic"),
                author_agent_id=_agent(event, "author_agent_id"),
                payload=dict(payload),
                occurred_at=event.occurred_at,
            )
        )

    def latest(self, topic: str | None = None) -> BoardPost | None:
        for post in reversed(self.posts):
            if topic is None or post.topic == topic:
                return post
        return None

    def snapshot(self) -> object:
        return tuple(self.posts)


# ---- ClusterGraphProjection ------------------------------------------------
@dataclass(frozen=True, slots=True)
class ClusterNode:
    agent_id: AgentId
    role: str
    mentor_id: AgentId | None
    cluster_id: ClusterId
    state: str


class ClusterGraphProjection:
    name = "cluster_graph"

    def __init__(self) -> None:
        self.nodes: dict[AgentId, ClusterNode] = {}

    def reset(self) -> None:
        self.nodes.clear()

    def apply(self, event: DomainEvent) -> None:
        if event.type is EventType.AGENT_CREATED:
            agent_id = _agent(event, "agent_id")
            mentor_id = _optional_text(event, "mentor_id")
            self.nodes[agent_id] = ClusterNode(
                agent_id=agent_id,
                role=_text(event, "role"),
                mentor_id=AgentId(mentor_id) if mentor_id else None,
                cluster_id=ClusterId(_text(event, "cluster_id")),
                state="CREATED",
            )
            return
        state = {
            EventType.AGENT_IDLE: "IDLE",
            EventType.AGENT_RUNNING: "RUNNING",
            EventType.AGENT_FAILED: "FAILED",
            EventType.AGENT_CLOSED: "CLOSED",
        }.get(event.type)
        if state is None:
            return
        agent_id = _agent(event, "agent_id")
        node = self.nodes.get(agent_id)
        if node is not None:
            self.nodes[agent_id] = replace(node, state=state)

    def edges(self) -> tuple[tuple[AgentId, AgentId], ...]:
        return tuple(
            (node.mentor_id, node.agent_id)
            for node in self.nodes.values()
            if node.mentor_id is not None
        )

    def snapshot(self) -> object:
        return tuple(sorted(self.nodes.values(), key=lambda node: node.agent_id.value))


# ---- CandidateGraphProjection ----------------------------------------------
@dataclass(frozen=True, slots=True)
class CandidateNode:
    candidate_id: CandidateId
    parent_id: CandidateId | None
    direction_id: DirectionId
    author_agent_id: AgentId | None


class CandidateGraphProjection:
    name = "candidate_graph"

    def __init__(self) -> None:
        self.nodes: dict[CandidateId, CandidateNode] = {}

    def reset(self) -> None:
        self.nodes.clear()

    def apply(self, event: DomainEvent) -> None:
        if event.type is not EventType.CANDIDATE_COMMITTED:
            return
        candidate_id = CandidateId(_text(event, "candidate_id"))
        parent = _optional_text(event, "parent_id")
        author = _optional_text(event, "author_agent_id")
        self.nodes[candidate_id] = CandidateNode(
            candidate_id=candidate_id,
            parent_id=CandidateId(parent) if parent else None,
            direction_id=DirectionId(_text(event, "direction_id")),
            author_agent_id=AgentId(author) if author else None,
        )

    def snapshot(self) -> object:
        return tuple(sorted(self.nodes.values(), key=lambda node: node.candidate_id.value))


# ---- QueueProjection -------------------------------------------------------
@dataclass(frozen=True, slots=True)
class QueueEntry:
    lease_id: str
    device_id: str
    task_id: str
    owner_agent_id: str
    state: str


class QueueProjection:
    name = "queue_view"

    def __init__(self) -> None:
        self.entries: dict[str, QueueEntry] = {}

    def reset(self) -> None:
        self.entries.clear()

    def apply(self, event: DomainEvent) -> None:
        state = {
            EventType.HARDWARE_QUEUED: "QUEUED",
            EventType.HARDWARE_LEASED: "LEASED",
            EventType.HARDWARE_RELEASED: "RELEASED",
            EventType.HARDWARE_EXPIRED: "EXPIRED",
        }.get(event.type)
        if state is None:
            return
        self.entries[_text(event, "lease_id")] = QueueEntry(
            lease_id=_text(event, "lease_id"),
            device_id=_text(event, "device_id"),
            task_id=_text(event, "task_id"),
            owner_agent_id=_text(event, "owner_agent_id"),
            state=state,
        )

    def leased(self, device_id: str) -> QueueEntry | None:
        for entry in self.entries.values():
            if entry.device_id == device_id and entry.state == "LEASED":
                return entry
        return None

    def snapshot(self) -> object:
        return tuple(sorted(self.entries.values(), key=lambda entry: entry.lease_id))


# ---- ProjectionRunner ------------------------------------------------------
class Projection(Protocol):
    name: str

    def reset(self) -> None: ...

    def apply(self, event: DomainEvent) -> None: ...

    def snapshot(self) -> object: ...


class ProjectionRunner:
    def __init__(self, connection: sqlite3.Connection, projections: Sequence[Projection]) -> None:
        self.connection = connection
        self.projections = tuple(projections)
        self.events = EventStore(connection)

    def cursor(self, name: str) -> int:
        row = self.connection.execute(
            "SELECT last_seq FROM projections WHERE name = ?", (name,)
        ).fetchone()
        return int(row["last_seq"]) if row is not None else 0

    def apply_pending(self) -> int:
        applied = 0
        for projection in self.projections:
            cursor = self.cursor(projection.name)
            records = self.events.read_after_with_seq(cursor)
            for _, event in records:
                projection.apply(event)
            if records:
                self._set_cursor(projection.name, records[-1][0])
            applied += len(records)
        return applied

    def rebuild(self) -> None:
        for projection in self.projections:
            projection.reset()
            self.connection.execute("DELETE FROM projections WHERE name = ?", (projection.name,))
        self.apply_pending()

    def _set_cursor(self, name: str, seq: int) -> None:
        self.connection.execute(
            """
            INSERT INTO projections (name, last_seq, schema_version, updated_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(name) DO UPDATE SET
                last_seq = excluded.last_seq,
                schema_version = excluded.schema_version,
                updated_at = excluded.updated_at
            """,
            (name, seq, time_ns() // 1_000_000),
        )

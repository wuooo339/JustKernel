"""SQLite repositories for Cluster and Agent."""

from __future__ import annotations

import json
import sqlite3

from justkernel.agent.agent import AgentInstance
from justkernel.agent.skills import SkillRef
from justkernel.agent.state import AgentState, Role
from justkernel.cluster.cluster import Cluster
from justkernel.platform.persistence.errors import ConcurrencyError
from justkernel.shared.digest import Digest
from justkernel.shared.ids import AgentId, ClusterId
from justkernel.shared.json import canonical_json


# ---- ClusterRepository ------------------------------------------------------
class ClusterRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(self, cluster: Cluster) -> None:
        self.connection.execute(
            """
            INSERT INTO clusters (
                id, operator_id, supervisor_id, operator_spec_digest, start_mode,
                phase, baseline_candidate_id, continued_from_cluster_id, state,
                max_agents, best_candidate_id, report_id, created_at, closed_at,
                version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            self._values(cluster),
        )

    def update(self, cluster: Cluster, expected_version: int) -> int:
        cursor = self.connection.execute(
            """
            UPDATE clusters SET
                operator_id = ?, supervisor_id = ?, operator_spec_digest = ?,
                start_mode = ?, phase = ?, baseline_candidate_id = ?,
                continued_from_cluster_id = ?, state = ?, max_agents = ?,
                best_candidate_id = ?, report_id = ?, created_at = ?,
                closed_at = ?, version = version + 1
            WHERE id = ? AND version = ?
            """,
            (*self._values(cluster)[1:], cluster.id.value, expected_version),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyError(f"cluster {cluster.id} version conflict")
        return expected_version + 1

    def version(self, cluster_id: ClusterId) -> int:
        row = self.connection.execute(
            "SELECT version FROM clusters WHERE id = ?", (cluster_id.value,)
        ).fetchone()
        if row is None:
            raise KeyError(cluster_id)
        return int(row["version"])

    def _values(self, cluster: Cluster) -> tuple[object, ...]:
        return (
            cluster.id.value,
            cluster.operator_id,
            cluster.supervisor_id.value,
            cluster.operator_spec_ref.digest.value,
            cluster.start_mode.value,
            cluster.phase.value,
            cluster.baseline_candidate_id.value if cluster.baseline_candidate_id else None,
            cluster.continued_from_cluster_id.value if cluster.continued_from_cluster_id else None,
            cluster.state.value,
            cluster.max_agents,
            cluster.best_candidate_id.value if cluster.best_candidate_id else None,
            cluster.report_id,
            cluster.created_at,
            cluster.closed_at,
        )


# ---- AgentRepository --------------------------------------------------------
class AgentRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert(self, agent: AgentInstance) -> None:
        self.connection.execute(
            """
            INSERT INTO agents (
                id, cluster_id, role, mentor_id, model_profile, skills_json,
                state, session_id, created_at, closed_at, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            self._values(agent),
        )

    def update(self, agent: AgentInstance, expected_version: int) -> int:
        cursor = self.connection.execute(
            """
            UPDATE agents SET
                cluster_id = ?, role = ?, mentor_id = ?, model_profile = ?,
                skills_json = ?, state = ?, session_id = ?, created_at = ?,
                closed_at = ?, version = version + 1
            WHERE id = ? AND version = ?
            """,
            (*self._values(agent)[1:], agent.id.value, expected_version),
        )
        if cursor.rowcount != 1:
            raise ConcurrencyError(f"agent {agent.id} version conflict")
        return expected_version + 1

    def get(self, agent_id: AgentId) -> AgentInstance:
        row = self.connection.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id.value,)
        ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        skills = tuple(
            SkillRef(
                name=item["name"],
                version=item["version"],
                source_path=item["source_path"],
                digest=Digest(item["digest"]),
            )
            for item in json.loads(row["skills_json"])
        )
        return AgentInstance(
            id=AgentId(row["id"]),
            cluster_id=ClusterId(row["cluster_id"]),
            role=Role(row["role"]),
            mentor_id=AgentId(row["mentor_id"]) if row["mentor_id"] else None,
            model_profile=row["model_profile"],
            skills=skills,
            created_at=row["created_at"],
            state=AgentState(row["state"]),
            session_id=row["session_id"],
            closed_at=row["closed_at"],
        )

    def version(self, agent_id: AgentId) -> int:
        row = self.connection.execute(
            "SELECT version FROM agents WHERE id = ?", (agent_id.value,)
        ).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return int(row["version"])

    def _values(self, agent: AgentInstance) -> tuple[object, ...]:
        skills = canonical_json(
            [
                {
                    "name": skill.name,
                    "version": skill.version,
                    "source_path": skill.source_path,
                    "digest": skill.digest.value,
                }
                for skill in agent.skills
            ]
        )
        return (
            agent.id.value,
            agent.cluster_id.value,
            agent.role.value,
            agent.mentor_id.value if agent.mentor_id else None,
            agent.model_profile,
            skills,
            agent.state.value,
            agent.session_id,
            agent.created_at,
            agent.closed_at,
        )

"""Bootstrap GENERATE/IMPORT modes after a validated cluster start."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from justkernel.agent.agent import AgentInstance
from justkernel.agent.state import Role
from justkernel.application.candidate_service import CandidateService
from justkernel.application.ports import DirectionRepositoryPort
from justkernel.application.start_cluster_service import StartedCluster
from justkernel.candidate.candidate import CandidateVersion
from justkernel.cluster.direction import Direction
from justkernel.cluster.errors import DirectionError
from justkernel.cluster.state import ClusterPhase, ClusterState, DirectionState, StartMode
from justkernel.shared.ids import DirectionId


# ---- ImportedBootstrap ------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ImportedBootstrap:
    direction: Direction
    candidate: CandidateVersion


# ---- BootstrapService -------------------------------------------------------
class BootstrapService:
    def __init__(
        self,
        directions: DirectionRepositoryPort,
        candidates: CandidateService,
    ) -> None:
        self.directions = directions
        self.candidates = candidates

    def generate(
        self,
        *,
        started: StartedCluster,
        objective: str,
        constraints: tuple[str, ...] = (),
        created_at: int,
    ) -> Direction:
        mentor = self._mentor(started, StartMode.GENERATE, created_at)
        direction = self._new_direction(started, mentor, objective, constraints, created_at)
        direction.activate()
        self.directions.insert(direction)
        return direction

    def import_root(
        self,
        *,
        started: StartedCluster,
        source_files: Mapping[str, str],
        diff_artifact: str,
        import_id: str,
        objective: str,
        constraints: tuple[str, ...] = (),
        created_at: int,
    ) -> ImportedBootstrap:
        mentor = self._mentor(started, StartMode.IMPORT, created_at)
        direction = self._new_direction(started, mentor, objective, constraints, created_at)
        direction.activate()
        candidate = self.candidates.import_candidate(
            cluster_id=started.cluster.id,
            direction_id=direction.id,
            source_files=source_files,
            diff_artifact=diff_artifact,
            import_id=import_id,
            created_at=created_at,
        )
        self.directions.insert(direction)
        return ImportedBootstrap(direction, candidate)

    def _mentor(
        self,
        started: StartedCluster,
        mode: StartMode,
        created_at: int,
    ) -> AgentInstance:
        cluster = started.cluster
        if cluster.state is not ClusterState.RUNNING:
            raise DirectionError("cluster is not running")
        if cluster.phase is not ClusterPhase.BOOTSTRAPPING:
            raise DirectionError("cluster is not bootstrapping")
        if cluster.start_mode is not mode:
            raise DirectionError(f"cluster is not in {mode} mode")
        if created_at < cluster.created_at:
            raise DirectionError("direction time precedes cluster creation")
        if not started.mentors:
            raise DirectionError("bootstrap requires a mentor")
        mentor = started.mentors[0]
        if mentor.cluster_id != cluster.id or mentor.role is not Role.MENTOR:
            raise DirectionError("bootstrap mentor is invalid")
        if any(
            direction.mentor_id == mentor.id and direction.state is DirectionState.ACTIVE
            for direction in self.directions.list_by_cluster(cluster.id)
        ):
            raise DirectionError("mentor already has an active direction")
        return mentor

    def _new_direction(
        self,
        started: StartedCluster,
        mentor: AgentInstance,
        objective: str,
        constraints: tuple[str, ...],
        created_at: int,
    ) -> Direction:
        return Direction(
            id=DirectionId.generate(),
            cluster_id=started.cluster.id,
            mentor_id=mentor.id,
            objective=objective,
            constraints=constraints,
            created_at=created_at,
        )

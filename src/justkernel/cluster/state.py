"""Cluster and direction state enums."""

from __future__ import annotations

from enum import StrEnum


# ---- ClusterState -----------------------------------------------------------
class ClusterState(StrEnum):
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CONVERGING = "CONVERGING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


# ---- ClusterPhase -----------------------------------------------------------
class ClusterPhase(StrEnum):
    BOOTSTRAPPING = "BOOTSTRAPPING"
    OPTIMIZING = "OPTIMIZING"
    FINALIZING = "FINALIZING"


# ---- StartMode --------------------------------------------------------------
class StartMode(StrEnum):
    GENERATE = "GENERATE"
    IMPORT = "IMPORT"


# ---- DirectionState ---------------------------------------------------------
class DirectionState(StrEnum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"

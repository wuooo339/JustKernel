"""Cluster and direction transition errors."""

from __future__ import annotations

from justkernel.shared.errors import JustKernelError


# ---- ClusterError -----------------------------------------------------------
class ClusterError(JustKernelError):
    code = "invalid_cluster_transition"


# ---- DirectionError ---------------------------------------------------------
class DirectionError(JustKernelError):
    code = "invalid_direction_transition"

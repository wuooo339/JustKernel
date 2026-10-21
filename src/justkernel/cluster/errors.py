"""Cluster and direction transition errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- ClusterError -----------------------------------------------------------
class ClusterError(JustKernelError):
    code = ErrorCode.INVALID_CLUSTER_TRANSITION


# ---- DirectionError ---------------------------------------------------------
class DirectionError(JustKernelError):
    code = ErrorCode.INVALID_DIRECTION_TRANSITION

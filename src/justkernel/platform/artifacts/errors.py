"""Artifact store errors."""

from __future__ import annotations

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- ArtifactError ----------------------------------------------------------
class ArtifactError(JustKernelError):
    code = ErrorCode.ARTIFACT_INVALID


# ---- ArtifactMissingError ---------------------------------------------------
class ArtifactMissingError(ArtifactError):
    code = ErrorCode.ARTIFACT_MISSING


# ---- ArtifactCorruptError ---------------------------------------------------
class ArtifactCorruptError(ArtifactError):
    code = ErrorCode.ARTIFACT_CORRUPT

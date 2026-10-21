from __future__ import annotations

from justkernel.platform.artifacts.errors import ArtifactCorruptError, ArtifactMissingError
from justkernel.shared.error_codes import ErrorCode


# ---- artifact errors --------------------------------------------------------
def test_artifact_error_codes_are_stable() -> None:
    assert ArtifactMissingError.code is ErrorCode.ARTIFACT_MISSING
    assert ArtifactCorruptError.code is ErrorCode.ARTIFACT_CORRUPT

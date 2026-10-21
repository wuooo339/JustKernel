"""Best-selection state."""

from __future__ import annotations

from enum import StrEnum


# ---- SelectionState ---------------------------------------------------------
class SelectionState(StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    FAILED = "FAILED"

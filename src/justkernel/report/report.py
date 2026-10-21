"""Immutable exploration report."""

from __future__ import annotations

from dataclasses import dataclass

from justkernel.report.errors import ReportError
from justkernel.shared.ids import CandidateId, ClusterId, DirectionId, TestRecordId


# ---- _require_unique --------------------------------------------------------
def _require_unique(name: str, values: tuple[object, ...]) -> None:
    if len(set(values)) != len(values):
        raise ReportError(f"{name} must be unique")


# ---- ReportDirection --------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ReportDirection:
    direction_id: DirectionId
    objective: str
    outcome: str

    def __post_init__(self) -> None:
        if not self.objective or not self.outcome:
            raise ReportError("report direction objective and outcome must be non-empty")


# ---- ExplorationReport ------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ExplorationReport:
    id: str
    cluster_id: ClusterId
    best_candidate_id: CandidateId | None
    revision: int
    directions: tuple[ReportDirection, ...]
    candidates: tuple[CandidateId, ...]
    records: tuple[TestRecordId, ...]
    failures: tuple[str, ...]
    decision: str
    created_at: int

    def __post_init__(self) -> None:
        if not self.id or not self.decision:
            raise ReportError("report id and decision must be non-empty")
        if self.revision < 1:
            raise ReportError("report revision must be positive")
        if not self.directions:
            raise ReportError("report must include at least one direction")
        if any(not failure for failure in self.failures):
            raise ReportError("failure entries must be non-empty")
        if self.created_at < 0:
            raise ReportError("created_at must be non-negative")
        _require_unique("candidates", self.candidates)
        _require_unique("records", self.records)
        if self.best_candidate_id is not None and self.best_candidate_id not in self.candidates:
            raise ReportError("best candidate must be one of the report candidates")

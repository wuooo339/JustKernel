"""Independent best-candidate selection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Self

from justkernel.candidate.errors import BestSelectionError
from justkernel.candidate.state import SelectionState
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    BestSelectionId,
    CandidateId,
    ClusterId,
    TaskId,
    TestRecordId,
)


# ---- _require_unique --------------------------------------------------------
def _require_unique(name: str, values: tuple[object, ...]) -> None:
    if not values:
        raise BestSelectionError(f"{name} must be non-empty")
    if len(set(values)) != len(values):
        raise BestSelectionError(f"{name} must be unique")


# ---- BestSelection ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BestSelection:
    id: BestSelectionId
    cluster_id: ClusterId
    candidate_id: CandidateId
    policy_digest: Digest
    nomination_record_ids: tuple[TestRecordId, ...]
    reason: str
    created_at: int
    final_task_ids: tuple[TaskId, ...] = ()
    final_record_ids: tuple[TestRecordId, ...] = ()
    state: SelectionState = SelectionState.PENDING

    def __post_init__(self) -> None:
        _require_unique("nomination_record_ids", self.nomination_record_ids)
        if not self.reason:
            raise BestSelectionError("reason must be non-empty")
        if self.created_at < 0:
            raise BestSelectionError("created_at must be non-negative")
        if self.state is SelectionState.PENDING:
            if self.final_task_ids or self.final_record_ids:
                raise BestSelectionError("pending selection must not have final evidence")
        elif self.state is SelectionState.VALIDATED:
            _require_unique("final_task_ids", self.final_task_ids)
            _require_unique("final_record_ids", self.final_record_ids)
        else:
            if self.final_task_ids:
                _require_unique("final_task_ids", self.final_task_ids)
            if self.final_record_ids:
                _require_unique("final_record_ids", self.final_record_ids)

    def validated(
        self,
        final_task_ids: tuple[TaskId, ...],
        final_record_ids: tuple[TestRecordId, ...],
    ) -> Self:
        if self.state is not SelectionState.PENDING:
            raise BestSelectionError(f"cannot validate selection in {self.state}")
        _require_unique("final_task_ids", final_task_ids)
        _require_unique("final_record_ids", final_record_ids)
        return replace(
            self,
            state=SelectionState.VALIDATED,
            final_task_ids=final_task_ids,
            final_record_ids=final_record_ids,
        )

    def failed(self, reason: str) -> Self:
        if self.state is not SelectionState.PENDING:
            raise BestSelectionError(f"cannot fail selection in {self.state}")
        if not reason:
            raise BestSelectionError("failure reason must be non-empty")
        return replace(self, state=SelectionState.FAILED, reason=reason)

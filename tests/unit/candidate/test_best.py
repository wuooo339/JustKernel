from __future__ import annotations

import pytest

from justkernel.candidate.best import BestSelection
from justkernel.candidate.errors import BestSelectionError
from justkernel.candidate.state import SelectionState
from justkernel.shared.digest import Digest
from justkernel.shared.ids import (
    BestSelectionId,
    CandidateId,
    ClusterId,
    TaskId,
)
from justkernel.shared.ids import (
    TestRecordId as RecordId,
)


# ---- helpers ----------------------------------------------------------------
def _selection(**overrides: object) -> BestSelection:
    values: dict[str, object] = {
        "id": BestSelectionId.generate(),
        "cluster_id": ClusterId.generate(),
        "candidate_id": CandidateId.generate(),
        "policy_digest": Digest.from_text("policy"),
        "nomination_record_ids": (RecordId.generate(),),
        "reason": "best available evidence",
        "created_at": 0,
    }
    values.update(overrides)
    return BestSelection(**values)


# ---- nomination -------------------------------------------------------------
def test_selection_requires_nomination_and_reason() -> None:
    with pytest.raises(BestSelectionError):
        _selection(nomination_record_ids=())
    with pytest.raises(BestSelectionError):
        _selection(reason="")

    record = RecordId.generate()
    with pytest.raises(BestSelectionError):
        _selection(nomination_record_ids=(record, record))


# ---- validation -------------------------------------------------------------
def test_pending_selection_can_be_validated() -> None:
    selection = _selection()
    task = TaskId.generate()
    record = RecordId.generate()

    validated = selection.validated((task,), (record,))

    assert validated.state is SelectionState.VALIDATED
    assert validated.final_task_ids == (task,)
    assert validated.final_record_ids == (record,)
    assert selection.state is SelectionState.PENDING


def test_pending_selection_can_fail() -> None:
    selection = _selection()
    failed = selection.failed("no comparable profile")

    assert failed.state is SelectionState.FAILED
    assert failed.reason == "no comparable profile"
    assert selection.state is SelectionState.PENDING


# ---- guards -----------------------------------------------------------------
def test_validated_selection_rejects_further_changes() -> None:
    selection = _selection()
    validated = selection.validated(
        (TaskId.generate(),),
        (RecordId.generate(),),
    )

    with pytest.raises(BestSelectionError):
        validated.validated((TaskId.generate(),), (RecordId.generate(),))
    with pytest.raises(BestSelectionError):
        validated.failed("late")


def test_final_validation_requires_both_lists_and_unique_ids() -> None:
    selection = _selection()
    task = TaskId.generate()
    record = RecordId.generate()

    with pytest.raises(BestSelectionError):
        selection.validated((), (record,))
    with pytest.raises(BestSelectionError):
        selection.validated((task,), ())
    with pytest.raises(BestSelectionError):
        selection.validated((task, task), (record,))
    with pytest.raises(BestSelectionError):
        selection.validated((task,), (record, record))


def test_terminal_constructor_fields_are_consistent() -> None:
    with pytest.raises(BestSelectionError):
        _selection(state=SelectionState.VALIDATED)
    with pytest.raises(BestSelectionError):
        _selection(final_task_ids=(TaskId.generate(),))
    with pytest.raises(BestSelectionError):
        _selection(state=SelectionState.FAILED, reason="")

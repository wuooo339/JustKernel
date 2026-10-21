from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from justkernel.report.errors import ReportError
from justkernel.report.report import ExplorationReport, ReportDirection
from justkernel.shared.ids import CandidateId, ClusterId, DirectionId
from justkernel.shared.ids import TestRecordId as RecordId


# ---- helpers ----------------------------------------------------------------
def _direction() -> ReportDirection:
    return ReportDirection(
        direction_id=DirectionId.generate(),
        objective="improve memory access",
        outcome="candidate improved",
    )


def _report(**overrides: object) -> ExplorationReport:
    candidate = CandidateId.generate()
    values: dict[str, object] = {
        "id": "report-1",
        "cluster_id": ClusterId.generate(),
        "best_candidate_id": candidate,
        "revision": 1,
        "directions": (_direction(),),
        "candidates": (candidate,),
        "records": (RecordId.generate(),),
        "failures": ("compile failure on first candidate",),
        "decision": "best full test pass",
        "created_at": 0,
    }
    values.update(overrides)
    return ExplorationReport(**values)


# ---- report -----------------------------------------------------------------
def test_report_with_best_candidate() -> None:
    report = _report()
    assert report.best_candidate_id in report.candidates


def test_report_can_have_no_best() -> None:
    assert _report(best_candidate_id=None).best_candidate_id is None


def test_best_must_be_one_of_the_candidates() -> None:
    with pytest.raises(ReportError):
        _report(best_candidate_id=CandidateId.generate())


def test_report_revision_and_content_validation() -> None:
    with pytest.raises(ReportError):
        _report(revision=0)
    with pytest.raises(ReportError):
        _report(decision="")
    with pytest.raises(ReportError):
        _report(directions=())
    with pytest.raises(ReportError):
        _report(failures=("",))

    candidate = CandidateId.generate()
    with pytest.raises(ReportError):
        _report(candidates=(candidate, candidate), best_candidate_id=candidate)


def test_report_is_frozen() -> None:
    report = _report()

    with pytest.raises(FrozenInstanceError):
        report.decision = "other"

from __future__ import annotations

from justkernel.agent.errors import AgentError
from justkernel.candidate.errors import BestSelectionError, CandidateError
from justkernel.cluster.errors import ClusterError, DirectionError
from justkernel.cluster.invariants import InvariantError
from justkernel.cluster.operator_spec import OperatorSpecError
from justkernel.comm.errors import AccessDeniedError, ChannelError, MessageError
from justkernel.platform.persistence.errors import ConcurrencyError
from justkernel.report.errors import ReportError
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import (
    InvalidClockError,
    InvalidDigestError,
    InvalidIdError,
    InvalidJsonError,
    InvalidPrincipalError,
    InvalidProjectPathError,
)
from justkernel.shared.events import EventError
from justkernel.task.context import TaskContextError
from justkernel.task.errors import TaskError
from justkernel.testing.errors import LeaseError
from justkernel.testing.errors import TestRecordError as RecordError
from justkernel.testing.policy import PolicyError

ERROR_CLASSES = (
    AgentError,
    BestSelectionError,
    CandidateError,
    ClusterError,
    DirectionError,
    InvariantError,
    AccessDeniedError,
    ChannelError,
    MessageError,
    ReportError,
    ConcurrencyError,
    InvalidClockError,
    InvalidDigestError,
    InvalidIdError,
    InvalidJsonError,
    InvalidPrincipalError,
    InvalidProjectPathError,
    EventError,
    TaskError,
    LeaseError,
    RecordError,
    PolicyError,
    OperatorSpecError,
    TaskContextError,
)


# ---- registry ---------------------------------------------------------------
def test_all_error_classes_use_the_registry() -> None:
    registry = set(ErrorCode)

    for error_type in ERROR_CLASSES:
        assert error_type.code in registry, error_type


def test_error_codes_are_unique() -> None:
    assert len({error_type.code for error_type in ERROR_CLASSES}) == len(ERROR_CLASSES)


def test_known_error_code_values_are_stable() -> None:
    assert ErrorCode.INVALID_ID == "invalid_id"
    assert ErrorCode.ACL_DENIED == "acl.denied"
    assert ErrorCode.INVARIANT_VIOLATION == "invariant.violation"
    assert ErrorCode.INVALID_EVENT == "invalid_event"

from __future__ import annotations

from justkernel.shared.errors import (
    InvalidClockError,
    InvalidDigestError,
    InvalidIdError,
    InvalidJsonError,
    InvalidPrincipalError,
    InvalidProjectPathError,
    JustKernelError,
)


# ---- stable error codes -----------------------------------------------------
def test_error_exposes_code_message_and_string() -> None:
    error = InvalidIdError("bad id")

    assert isinstance(error, JustKernelError)
    assert error.code == "invalid_id"
    assert error.message == "bad id"
    assert str(error) == "invalid_id: bad id"


def test_shared_errors_have_stable_codes() -> None:
    expected = {
        InvalidDigestError: "invalid_digest",
        InvalidJsonError: "invalid_json",
        InvalidClockError: "invalid_clock",
        InvalidPrincipalError: "invalid_principal",
        InvalidProjectPathError: "invalid_project_path",
    }

    for error_type, code in expected.items():
        assert error_type.code == code

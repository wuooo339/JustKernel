"""RFC7807 problem responses and stable error/status mapping."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse

from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- API errors -------------------------------------------------------------
class ApiError(JustKernelError):
    code = ErrorCode.REQUEST_INVALID


class IdempotencyConflictError(JustKernelError):
    code = ErrorCode.IDEMPOTENCY_CONFLICT


# ---- ProblemDetail ----------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProblemDetail:
    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
        }
        if self.instance is not None:
            payload["instance"] = self.instance
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        return payload


# ---- status mapping ---------------------------------------------------------
_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.ACL_DENIED: 403,
    ErrorCode.ARTIFACT_MISSING: 404,
    ErrorCode.REGISTRY_CONFLICT: 409,
    ErrorCode.REGISTRY_OPERATOR_ACTIVE: 409,
    ErrorCode.CONCURRENCY_CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.OPERATOR_SPEC_INCOMPLETE: 422,
    ErrorCode.INVALID_ID: 422,
    ErrorCode.INVALID_DIGEST: 422,
    ErrorCode.INVALID_JSON: 422,
    ErrorCode.INVALID_CLOCK: 422,
    ErrorCode.INVALID_PRINCIPAL: 422,
    ErrorCode.INVALID_PROJECT_PATH: 422,
    ErrorCode.INVALID_POLICY: 422,
    ErrorCode.INVALID_CLUSTER_TRANSITION: 409,
    ErrorCode.INVALID_DIRECTION_TRANSITION: 409,
    ErrorCode.INVALID_AGENT_TRANSITION: 409,
    ErrorCode.INVALID_TASK_TRANSITION: 409,
    ErrorCode.INVALID_TASK_CONTEXT: 422,
    ErrorCode.INVALID_CANDIDATE: 422,
    ErrorCode.INVALID_BEST_SELECTION: 422,
    ErrorCode.INVALID_TEST_RECORD: 422,
    ErrorCode.INVALID_TOOL_JOB: 409,
    ErrorCode.INVALID_LEASE_TRANSITION: 409,
    ErrorCode.INVALID_REPORT: 422,
    ErrorCode.INVALID_CHANNEL: 422,
    ErrorCode.INVALID_MESSAGE: 422,
    ErrorCode.INVALID_EVENT: 422,
    ErrorCode.REQUEST_INVALID: 422,
}


def status_for(error: JustKernelError) -> int:
    return _STATUS_BY_CODE.get(error.code, 400)


def problem_from_error(
    error: JustKernelError,
    *,
    instance: str | None = None,
    request_id: str | None = None,
) -> ProblemDetail:
    status = status_for(error)
    code = str(error.code)
    return ProblemDetail(
        type=f"https://justkernel.dev/problems/{code}",
        title=HTTPStatus(status).phrase,
        status=status,
        code=code,
        detail=error.message,
        instance=instance,
        request_id=request_id,
    )


def problem_response(
    problem: ProblemDetail,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.to_dict(),
        media_type="application/problem+json",
        headers=headers,
    )


def request_id_for(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")

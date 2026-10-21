"""FastAPI application skeleton and exception contract."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from justkernel import __version__
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.errors import (
    ApiError,
    ProblemDetail,
    problem_from_error,
    problem_response,
    request_id_for,
)
from justkernel.platform.http.idempotency import IdempotencyMiddleware, IdempotencyStore
from justkernel.platform.http.routes_a2a import register_a2a_routes
from justkernel.platform.http.routes_agents import register_agent_routes
from justkernel.platform.http.routes_candidates import (
    register_candidate_routes,
    register_record_routes,
)
from justkernel.platform.http.routes_cluster import (
    register_cluster_command_routes,
    register_cluster_read_routes,
)
from justkernel.platform.http.routes_events import register_event_routes
from justkernel.platform.http.routes_misc import (
    register_board_routes,
    register_hardware_routes,
    register_message_routes,
    register_report_routes,
)
from justkernel.platform.http.routes_tasks import register_task_routes
from justkernel.shared.error_codes import ErrorCode
from justkernel.shared.errors import JustKernelError


# ---- exception handlers -----------------------------------------------------
async def _handle_justkernel(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, JustKernelError)
    return problem_response(
        problem_from_error(
            error,
            instance=str(request.url),
            request_id=request_id_for(request),
        )
    )


async def _handle_validation(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    problem = ProblemDetail(
        type="https://justkernel.dev/problems/request.invalid",
        title="Unprocessable Content",
        status=422,
        code=str(ErrorCode.REQUEST_INVALID),
        detail="request validation failed",
        instance=str(request.url),
        request_id=request_id_for(request),
    )
    return problem_response(problem)


async def _handle_api_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    return problem_response(
        problem_from_error(
            error,
            instance=str(request.url),
            request_id=request_id_for(request),
        )
    )


def _install_handlers(app: FastAPI) -> None:
    app.add_exception_handler(JustKernelError, _handle_justkernel)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(ApiError, _handle_api_error)


# ---- create_app -------------------------------------------------------------
def _register_api_routes(app: FastAPI, context: ApiContext) -> None:
    register_cluster_read_routes(app, context)
    register_cluster_command_routes(app, context)
    register_a2a_routes(app, context)
    register_agent_routes(app, context)
    register_task_routes(app, context)
    register_candidate_routes(app, context)
    register_record_routes(app, context)
    register_report_routes(app, context)
    register_board_routes(app, context)
    register_message_routes(app, context)
    register_hardware_routes(app, context)
    if context.events is not None:
        register_event_routes(app, context)


def create_app(
    *,
    idempotency: IdempotencyStore | None = None,
    context: ApiContext | None = None,
) -> FastAPI:
    app = FastAPI(title="JustKernel", version=__version__)
    app.add_middleware(
        IdempotencyMiddleware,
        store=idempotency or IdempotencyStore(),
    )
    _install_handlers(app)
    if context is not None:
        _register_api_routes(app, context)

    @app.get("/api/v1/system/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app

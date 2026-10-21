"""Idempotency-key response cache and middleware."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from threading import Lock
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from justkernel.platform.http.errors import (
    IdempotencyConflictError,
    problem_from_error,
    problem_response,
)

IDEMPOTENCY_HEADER = "Idempotency-Key"


# ---- CachedResponse ---------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CachedResponse:
    fingerprint: str
    status_code: int
    body: bytes
    content_type: str


# ---- IdempotencyStore -------------------------------------------------------
class IdempotencyStore:
    def __init__(self) -> None:
        self._entries: dict[str, CachedResponse] = {}
        self._lock = Lock()

    def begin(self, key: str, fingerprint: str) -> CachedResponse | None:
        if not key:
            raise IdempotencyConflictError("idempotency key must be non-empty")
        with self._lock:
            cached = self._entries.get(key)
            if cached is None:
                return None
            if cached.fingerprint != fingerprint:
                raise IdempotencyConflictError("idempotency key reused with a different request")
            return cached

    def put(
        self,
        key: str,
        fingerprint: str,
        status_code: int,
        body: bytes,
        content_type: str,
    ) -> None:
        with self._lock:
            self._entries[key] = CachedResponse(fingerprint, status_code, body, content_type)


def fingerprint_bytes(body: bytes) -> str:
    return sha256(body).hexdigest()


# ---- Middleware -------------------------------------------------------------
class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, store: IdempotencyStore) -> None:
        super().__init__(app)
        self.store = store

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "POST":
            return await call_next(request)
        key = request.headers.get(IDEMPOTENCY_HEADER)
        if not key:
            return await call_next(request)
        body = await request.body()
        fingerprint = fingerprint_bytes(body)
        try:
            cached = self.store.begin(key, fingerprint)
        except IdempotencyConflictError as error:
            request_id = request.headers.get("X-Request-ID")
            return problem_response(
                problem_from_error(error, instance=str(request.url), request_id=request_id)
            )
        if cached is not None:
            return Response(
                content=cached.body,
                status_code=cached.status_code,
                media_type=cached.content_type,
            )
        response = await call_next(request)
        if 200 <= response.status_code < 300:
            iterator = getattr(response, "body_iterator", None)
            if iterator is None:
                return response
            chunks: list[bytes] = []
            async for chunk in iterator:
                chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode())
            content = b"".join(chunks)
            content_type = response.headers.get("content-type", "application/json")
            self.store.put(key, fingerprint, response.status_code, content, content_type)
            return Response(
                content=content,
                status_code=response.status_code,
                media_type=content_type,
                headers=dict(response.headers),
            )
        return response

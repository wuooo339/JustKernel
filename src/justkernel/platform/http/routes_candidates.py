"""Candidate and TestRecord read routes."""

from __future__ import annotations

from fastapi import FastAPI, Request, Response

from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.errors import NotFoundError
from justkernel.platform.http.routes_common import (
    candidate,
    candidate_view,
    cluster,
    record,
    record_view,
    require_human,
    require_record_download,
)


def register_candidate_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/clusters/{cluster_id}/candidates")
    def list_candidates(cluster_id: str) -> list[object]:
        item = cluster(ctx, cluster_id)
        return [
            candidate_view(ctx, candidate_obj)
            for candidate_obj in ctx.candidates.list_by_cluster(item.id)
        ]

    @app.get("/api/v1/candidates/{candidate_id}")
    def get_candidate(candidate_id: str) -> object:
        return candidate_view(ctx, candidate(ctx, candidate_id))

    @app.get("/api/v1/candidates/{candidate_id}/source")
    def get_source(candidate_id: str, request: Request) -> dict[str, object]:
        require_human(request)
        item = candidate(ctx, candidate_id)
        return {
            "source_digest": item.source.digest.value,
            "files": [
                {
                    "path": path.value,
                    "content": ctx.redactor.redact_text(content),
                }
                for path, content in item.source.files
            ],
        }

    @app.get("/api/v1/candidates/{candidate_id}/records")
    def list_records(candidate_id: str) -> list[object]:
        item = candidate(ctx, candidate_id)
        return [
            record_view(ctx, record_obj) for record_obj in ctx.records.list_by_candidate(item.id)
        ]


def register_record_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/records/{record_id}")
    def get_record(record_id: str) -> object:
        return record_view(ctx, record(ctx, record_id))

    @app.get("/api/v1/records/{record_id}/download")
    def download_record(record_id: str, request: Request) -> Response:
        item = record(ctx, record_id)
        require_record_download(ctx, item, request)
        if ctx.artifacts is None:
            raise NotFoundError("artifact store is not configured")
        data = ctx.artifacts.get_bytes(item.artifact.digest)
        return Response(
            content=data,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{item.id.value}.zip"',
                "X-Artifact-Digest": item.artifact.digest.value,
            },
        )

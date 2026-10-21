"""Redacted export and report download routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.responses import Response

from justkernel.comm.errors import AccessDeniedError
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.routes_common import (
    candidate_view,
    cluster,
    cluster_view,
    record_view,
    report,
    report_view,
)
from justkernel.shared.ids import ClusterId


def _require_human(request: Request) -> None:
    if request.headers.get("X-Human", "").lower() not in {"1", "true", "yes"}:
        raise AccessDeniedError("export requires an explicit human request")


def _candidate_payloads(
    ctx: ApiContext, cluster_id: ClusterId
) -> tuple[list[object], list[object]]:
    candidates = ctx.candidates.list_by_cluster(cluster_id)
    candidate_data: list[object] = []
    record_data: list[object] = []
    for item in candidates:
        candidate_data.append(asdict(candidate_view(ctx, item)))
        record_data.extend(
            asdict(record_view(ctx, record_obj))
            for record_obj in ctx.records.list_by_candidate(item.id)
        )
    return candidate_data, record_data


def _export_payload(ctx: ApiContext, cluster_id: str) -> dict[str, object]:
    item = cluster(ctx, cluster_id)
    candidates, records = _candidate_payloads(ctx, item.id)
    payload: dict[str, object] = {
        "cluster": asdict(cluster_view(ctx, item)),
        "candidates": candidates,
        "records": records,
    }
    if item.report_id is not None:
        payload["report"] = asdict(report_view(report(ctx, item)))
    redacted = ctx.redactor.redact(payload)
    if not isinstance(redacted, dict):
        return {}
    return redacted


def register_export_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/export")
    def export_cluster(cluster_id: str, request: Request) -> dict[str, object]:
        _require_human(request)
        return _export_payload(ctx, cluster_id)

    @app.get("/api/v1/clusters/{cluster_id}/report/download")
    def download_report(cluster_id: str, request: Request) -> Response:
        _require_human(request)
        value = report_view(report(ctx, cluster(ctx, cluster_id)))
        lines = [
            f"# Exploration Report {value.id}",
            f"Best: {value.best_candidate_id}",
            f"Decision: {value.decision}",
            "",
            *[f"- {failure}" for failure in value.failures],
        ]
        text = ctx.redactor.redact_text("\n".join(lines) + "\n")
        return Response(
            content=text,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{value.id}.md"'},
        )

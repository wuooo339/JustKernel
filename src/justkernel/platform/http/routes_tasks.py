"""Task and tool-job read routes."""

from __future__ import annotations

from fastapi import FastAPI, Query, Request

from justkernel.comm.errors import AccessDeniedError
from justkernel.platform.http.context import ApiContext
from justkernel.platform.http.dtos import ToolJobReadView
from justkernel.platform.http.errors import NotFoundError
from justkernel.platform.http.routes_common import (
    caller_agent,
    cluster,
    require_task_reader,
    task,
    task_view,
)
from justkernel.shared.ids import TaskId


def _tasks(ctx: ApiContext, cluster_id: str | None, state: str | None) -> list[object]:
    if cluster_id is None:
        raise NotFoundError("cluster filter is required")
    cluster_obj = cluster(ctx, cluster_id)
    tasks = ctx.tasks.list_by_cluster(cluster_obj.id)
    if state is not None:
        tasks = tuple(item for item in tasks if item.state.value == state)
    return [task_view(item) for item in tasks]


def register_task_routes(app: FastAPI, ctx: ApiContext) -> None:
    @app.get("/api/v1/tasks")
    def list_tasks(
        cluster_id: str | None = Query(default=None, alias="cluster"),
        state: str | None = None,
    ) -> list[object]:
        return _tasks(ctx, cluster_id, state)

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str) -> object:
        return task_view(task(ctx, task_id))

    @app.get("/api/v1/tasks/{task_id}/context")
    def get_context(task_id: str, request: Request) -> dict[str, object]:
        item = task(ctx, task_id)
        require_task_reader(item, request)
        return {
            "task_id": item.id.value,
            "context_ref": item.context_ref,
            "context_digest": item.context_digest.value,
            "operator_spec_digest": item.operator_spec_ref.digest.value,
        }

    @app.get("/api/v1/tool-jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> ToolJobReadView:
        try:
            job = ctx.jobs.get(job_id)
            item = ctx.tasks.get(TaskId(job.task_id.value))
        except (KeyError, ValueError) as error:
            raise NotFoundError("tool job not found") from error
        if caller_agent(request) != item.worker_id:
            raise AccessDeniedError("only the task worker can read this job")
        return ToolJobReadView(
            job_id=job.id,
            task_id=job.task_id.value,
            state=job.state.value,
            record_id=job.record_id,
            error=job.error,
            queue_position=job.queue_position,
        )

"""Role-aware tool registry with object-level grants."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from justkernel.agent.state import Role
from justkernel.application.errors import ToolAccessError, ToolNotFoundError
from justkernel.comm.capabilities import Tool, can_use_tool, tools_for
from justkernel.shared.ids import AgentId, ClusterId, TaskId

PRIVILEGED_CANDIDATE_ROLES = frozenset({Role.SUPERVISOR, Role.MENTOR})
PRIVILEGED_RECORD_ROLES = frozenset({Role.SUPERVISOR, Role.MENTOR})


# ---- ObjectKind -------------------------------------------------------------
class ObjectKind(StrEnum):
    CANDIDATE = "CANDIDATE"
    TASK = "TASK"
    CONTEXT = "CONTEXT"
    ARTIFACT = "ARTIFACT"
    TEST_RECORD = "TEST_RECORD"
    TOOL_JOB = "TOOL_JOB"
    BOARD = "BOARD"


# ---- ObjectRef --------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ObjectRef:
    kind: ObjectKind
    id: str


# ---- ToolContext ------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ToolContext:
    role: Role
    agent_id: AgentId
    cluster_id: ClusterId
    task_id: TaskId | None = None
    allowed_tasks: frozenset[str] = frozenset()
    allowed_candidates: frozenset[str] = frozenset()
    allowed_records: frozenset[str] = frozenset()
    allowed_tool_jobs: frozenset[str] = frozenset()
    allowed_artifacts: frozenset[str] = frozenset()


# ---- ToolRegistry -----------------------------------------------------------
class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[Tool, Callable[..., object]] = {}

    def register(self, tool: Tool, handler: Callable[..., object]) -> None:
        self._handlers[tool] = handler

    def available(self, role: Role) -> tuple[Tool, ...]:
        return tuple(sorted(tools_for(role), key=lambda tool: tool.value))

    def authorize(
        self,
        context: ToolContext,
        tool: Tool,
        object_ref: ObjectRef | None = None,
    ) -> None:
        if not can_use_tool(context.role, tool):
            raise ToolAccessError(f"{context.role} cannot use {tool.value}")
        if object_ref is None or object_ref.kind is ObjectKind.BOARD:
            return
        self._authorize_object(context, object_ref)

    def invoke(
        self,
        context: ToolContext,
        tool: Tool,
        object_ref: ObjectRef | None = None,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.authorize(context, tool, object_ref)
        handler = self._handlers.get(tool)
        if handler is None:
            raise ToolNotFoundError(f"tool has no registered handler: {tool.value}")
        return handler(object_ref, *args, **kwargs)

    def _authorize_object(self, context: ToolContext, reference: ObjectRef) -> None:
        if reference.kind is ObjectKind.CANDIDATE:
            if context.role in PRIVILEGED_CANDIDATE_ROLES:
                return
            allowed = context.allowed_candidates
        elif reference.kind is ObjectKind.TASK:
            if reference.id == (context.task_id.value if context.task_id else None):
                return
            allowed = context.allowed_tasks
        elif reference.kind in (ObjectKind.CONTEXT, ObjectKind.ARTIFACT):
            allowed = context.allowed_artifacts
        elif reference.kind is ObjectKind.TEST_RECORD:
            if context.role in PRIVILEGED_RECORD_ROLES:
                return
            allowed = context.allowed_records
        else:
            allowed = context.allowed_tool_jobs
        if reference.id not in allowed:
            raise ToolAccessError(
                f"{context.role} is not authorized for {reference.kind.value} {reference.id}"
            )

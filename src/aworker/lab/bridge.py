"""A2A is the transport; every dispatched team executes the same Deep Agents graph."""

import asyncio
import json
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, Task, TaskState, TaskStatus
from pydantic import BaseModel, ConfigDict, Field

from aworker.lab.service import LabService
from aworker.server.credentials import LLMCredential
from aworker.server.workspace import Workspace
from aworker.swarm.member import MemberAgent
from aworker.swarm.swarm import Swarm

logger = logging.getLogger(__name__)


# ---- TeamTask ---------------------------------------------------------------
class TeamTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    team: str = Field(min_length=1, max_length=64)
    task: str = Field(min_length=1, max_length=100_000)


# ---- MessageCommand ---------------------------------------------------------
class MessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = "message"
    team: str
    recipient: str
    message: str = Field(min_length=1, max_length=8000)
    artifact: str | None = None
    delivery_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


# ---- deliver_message --------------------------------------------------------
def deliver_message(service: LabService, text: str) -> str | None:
    if json.loads(text).get("action") != "message":
        return None
    command = MessageCommand.model_validate_json(text)
    if command.team == "judger":
        key = service.judger.notices.receive(command)
        return json.dumps({"id": key, "transport": "a2a"})
    if command.delivery_id:
        raise ValueError("system delivery identity cannot be used by a team")
    service.team_folder(command.team)
    service.team_folder(command.recipient)
    key = service.store.message(
        command.team, command.recipient, command.message, command.artifact, transport="a2a"
    )
    return json.dumps({"id": key, "transport": "a2a"})


# ---- TeamSwarm --------------------------------------------------------------
class TeamSwarm(Swarm):
    def __init__(self, service: LabService):
        super().__init__(service.settings)
        self.service = service

    # ---- live card and dispatch --------------------------------------------
    @property
    def members(self) -> tuple[MemberAgent, ...]:
        return tuple(
            MemberAgent(
                name=t["id"],
                description="Deep Agents team / " + t["model"],
                system_prompt="Unified kernel engineering team",
                model=t["model"],
            )
            for t in self.service.store.snapshot()["teams"]
            if t["active"] and t["runtime"] == "deepagents"
        )

    async def respond(
        self,
        prompt: str,
        thread_id: str,
        credential: LLMCredential | None = None,
        workspace: Workspace | None = None,
    ) -> str:
        if credential or workspace:
            raise ValueError(
                "lab requests select server model profiles and registered team workspaces"
            )
        if result := deliver_message(self.service, prompt):
            return result
        command = TeamTask.model_validate_json(prompt)
        key = self.service.start_operation(command.team, "run", command.task)
        return await wait_result(self.service, key)


# ---- wait_result ------------------------------------------------------------
async def wait_result(service: LabService, key: str) -> str:
    task = service._operations.get(key)
    if task:
        await asyncio.shield(task)
    entry = next(o for o in service.store.snapshot()["operations"] if o["id"] == key)
    if entry["state"] != "completed":
        raise RuntimeError(entry["error"] or entry["state"])
    cursor, result = 0, "Completed"
    while batch := service.store.events(cursor):
        for event in batch:
            if event["kind"] == "control.completed" and event["data"].get("operation_id") == key:
                result = event["data"].get("result", "Completed")
        cursor = batch[-1]["seq"]
    return result if isinstance(result, str) else json.dumps(result)


# ---- TeamExecutor -----------------------------------------------------------
class TeamExecutor(AgentExecutor):
    def __init__(self, service: LabService):
        self.service = service
        self.tasks = {}

    # ---- A2A lifecycle ------------------------------------------------------
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        pump = None
        try:
            if context.current_task is None:
                await event_queue.enqueue_event(
                    Task(
                        id=context.task_id,
                        context_id=context.context_id,
                        status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                        history=[context.message],
                    )
                )
            if result := deliver_message(self.service, context.get_user_input()):
                await updater.submit()
                await updater.complete(updater.new_agent_message([Part(text=result)]))
                return
            command = TeamTask.model_validate_json(context.get_user_input())
            key = self.service.start_operation(command.team, "run", command.task)
            self.tasks[context.task_id] = key
            await updater.submit()
            await updater.start_work(
                updater.new_agent_message(
                    [Part(text="Deep Agents task started")],
                    metadata={"run_id": key, "team": command.team},
                )
            )
            pump = asyncio.create_task(self.progress(key, updater))
            answer = await wait_result(self.service, key)
            await updater.complete(updater.new_agent_message([Part(text=answer)]))
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                await updater.cancel()
            else:
                logger.error(
                    "A2A task %s failed: %s", context.task_id, self.service.redact(str(exc))
                )
                await updater.failed(
                    updater.new_agent_message([Part(text=self.service.redact(str(exc))[:2000])])
                )
        finally:
            self.tasks.pop(context.task_id, None)
            if pump:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)

    async def progress(self, key: str, updater: TaskUpdater):
        cursor = 0
        while True:
            for event in self.service.store.events(cursor):
                cursor = event["seq"]
                if event["kind"] == "stage.updated" and event["data"].get("run_id") == key:
                    data = event["data"]
                    await updater.start_work(
                        updater.new_agent_message(
                            [Part(text=f"{data['stage']} / {data['state']}: {data['message']}")],
                            metadata={"run_id": key, "event_id": cursor},
                        )
                    )
            await asyncio.sleep(0.5)

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        key = self.tasks.get(context.task_id)
        if key:
            self.service.cancel_operation(key)
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()

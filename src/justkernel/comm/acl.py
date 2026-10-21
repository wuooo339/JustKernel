"""Role/resource access control."""

from __future__ import annotations

from enum import StrEnum

from justkernel.agent.state import Role
from justkernel.comm.channels import Channel, ChannelKind
from justkernel.comm.errors import AccessDeniedError
from justkernel.shared.principal import Principal


# ---- Resource ---------------------------------------------------------------
class Resource(StrEnum):
    MENTOR_BOARD = "MENTOR_BOARD"
    CONSULTANT_BOARD = "CONSULTANT_BOARD"
    WORKER_CHANNEL = "WORKER_CHANNEL"
    HARDWARE_QUEUE = "HARDWARE_QUEUE"
    CONTROL = "CONTROL"


# ---- resource_for -----------------------------------------------------------
def resource_for(channel: Channel) -> Resource:
    if channel.kind is ChannelKind.MENTOR_BOARD:
        return Resource.MENTOR_BOARD
    if channel.kind is ChannelKind.CONSULTANT_BOARD:
        return Resource.CONSULTANT_BOARD
    if channel.kind is ChannelKind.WORKER:
        return Resource.WORKER_CHANNEL
    if channel.kind is ChannelKind.HARDWARE:
        return Resource.HARDWARE_QUEUE
    return Resource.CONTROL


# ---- can_read ---------------------------------------------------------------
def can_read(role: Role, actor: Principal, channel: Channel) -> bool:
    if actor.kind in ("human", "system"):
        return True
    if actor.kind != "agent":
        return False
    resource = resource_for(channel)
    if resource is Resource.MENTOR_BOARD:
        return role in (Role.SUPERVISOR, Role.MENTOR, Role.CONSULTANT)
    if resource is Resource.CONSULTANT_BOARD:
        return role in (Role.SUPERVISOR, Role.CONSULTANT)
    if resource is Resource.WORKER_CHANNEL:
        return actor.agent_id in (channel.mentor_id, channel.worker_id)
    if resource is Resource.HARDWARE_QUEUE:
        return role in (Role.TESTER, Role.PROFILER, Role.SUPERVISOR, Role.MENTOR)
    return False


# ---- can_write --------------------------------------------------------------
def can_write(role: Role, actor: Principal, channel: Channel) -> bool:
    if actor.kind == "system":
        return True
    if actor.kind != "agent":
        return False
    resource = resource_for(channel)
    if resource is Resource.MENTOR_BOARD:
        return role in (Role.SUPERVISOR, Role.MENTOR)
    if resource is Resource.CONSULTANT_BOARD:
        return role in (Role.SUPERVISOR, Role.CONSULTANT)
    if resource is Resource.WORKER_CHANNEL:
        return actor.agent_id in (channel.mentor_id, channel.worker_id)
    if resource is Resource.HARDWARE_QUEUE:
        return role in (Role.TESTER, Role.PROFILER)
    return False


# ---- require_read -----------------------------------------------------------
def require_read(role: Role, actor: Principal, channel: Channel) -> None:
    if not can_read(role, actor, channel):
        raise AccessDeniedError(f"{role} cannot read {channel.name}")


# ---- require_write ----------------------------------------------------------
def require_write(role: Role, actor: Principal, channel: Channel) -> None:
    if not can_write(role, actor, channel):
        raise AccessDeniedError(f"{role} cannot write {channel.name}")

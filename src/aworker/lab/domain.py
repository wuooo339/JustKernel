"""Typed public contracts shared by the coordinator, tools and dashboard."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


# ---- Stage ------------------------------------------------------------------
class Stage(StrEnum):
    INPUT = "input"
    SEARCH = "search"
    POLICY = "policy"
    QUEUE = "queue"
    EXECUTE = "execute"
    VERIFY = "verify"
    SHARE = "share"
    DISTILL = "distill"


# ---- StageUpdate ------------------------------------------------------------
class StageUpdate(BaseModel):
    stage: Stage
    state: Literal["started", "progress", "completed", "failed", "skipped"]
    message: str
    run_id: str | None = None
    agent: str = "coordinator"
    evidence: str | None = None


# ---- Specialist -------------------------------------------------------------
class Specialist(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,40}$")
    role: Literal["analyst", "implementer", "reviewer"]
    model: str | None = None


# ---- Experience -------------------------------------------------------------
class Experience(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    conditions: str = Field(min_length=5, max_length=4000)
    action: str = Field(min_length=5, max_length=4000)
    limitations: str = Field(min_length=5, max_length=4000)
    evidence_job: str = Field(min_length=1, max_length=64)
    scope: str = Field(default="RotaryPosEmb", min_length=1, max_length=80)

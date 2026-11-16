"""Wire schemas exchanged between the control plane and the host agent."""

from enum import StrEnum

from pydantic import BaseModel


class StackStatus(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


class DesiredState(BaseModel):
    active: str | None
    generation: int


class ObservedState(BaseModel):
    stack_id: str | None
    status: StackStatus
    generation: int
    error: str | None = None
    at: float

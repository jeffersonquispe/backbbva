from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class AgentRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    session_id: str
    iteration_number: int
    subagent: str
    status: AgentRunStatus
    prompt_ref: dict[str, str]
    created_at: datetime
    lease_expires_at: datetime | None = None
    error_code: str | None = None


class AgentRunRepository(Protocol):
    def create(self, run: AgentRun) -> AgentRun: ...

    def get(self, run_id: str) -> AgentRun | None: ...

    def update(self, run: AgentRun) -> AgentRun: ...

    def list_active(self, now: datetime, limit: int = 100) -> list[AgentRun]: ...

    def list_stale(self, now: datetime, limit: int = 100) -> list[AgentRun]: ...

    def extend_lease(self, run_id: str, until: datetime) -> bool:
        """Heartbeat: push the lease of a still-RUNNING run; False if it ended."""
        ...

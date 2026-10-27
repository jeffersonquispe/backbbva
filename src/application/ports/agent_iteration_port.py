from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class AgentIterationStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AgentIteration:
    session_id: str
    number: int
    status: AgentIterationStatus
    started_at: datetime
    finished_at: datetime | None = None
    run_ids: tuple[str, ...] = ()
    package_id: str | None = None
    decision: dict[str, Any] = field(default_factory=dict)


class AgentIterationRepository(Protocol):
    def create(self, iteration: AgentIteration) -> AgentIteration: ...

    def get(self, session_id: str, number: int) -> AgentIteration | None: ...

    def list_for_session(
        self, session_id: str, limit: int = 50
    ) -> list[AgentIteration]: ...

    def update(self, iteration: AgentIteration) -> AgentIteration: ...

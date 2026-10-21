from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from src.domain.agents.experiment import ComponentVersionReference


class AgentSessionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WAITING_USER = "WAITING_USER"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AgentSession:
    session_id: str
    mode: str
    status: AgentSessionStatus
    owner_id: str
    created_at: datetime
    updated_at: datetime
    scope: dict[str, Any] = field(default_factory=dict)
    objective_id: str | None = None
    objective_version: int | None = None
    budget_limits: dict[str, int] = field(default_factory=dict)
    prompt_versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    rev: int = 0
    message_seq: int = 0
    budget_renewals: int = 0
    baseline_components: tuple[ComponentVersionReference, ...] = ()


class AgentSessionRepository(Protocol):
    def create(self, session: AgentSession) -> AgentSession: ...

    def get(self, session_id: str) -> AgentSession | None: ...

    def list_by_owner(self, owner_id: str, limit: int = 50) -> list[AgentSession]: ...

    def list_by_status(
        self, status: AgentSessionStatus, limit: int = 50
    ) -> list[AgentSession]: ...

    def update(self, session: AgentSession, expected_rev: int) -> AgentSession: ...

    def acquire_lease(
        self, session_id: str, owner: str, now: datetime, expires_at: datetime
    ) -> AgentSession | None: ...

    def increment_message_seq(self, session_id: str) -> int: ...

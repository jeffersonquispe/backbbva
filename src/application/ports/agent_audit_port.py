from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AgentAuditEvent:
    session_id: str
    occurred_at: datetime
    event_id: str
    category: str
    status: str
    reason_code: str | None = None
    duration_ms: int | None = None
    cost_micros: int | None = None
    specialist: str | None = None
    tool: str | None = None
    actor: str | None = None
    actor_id: str | None = None
    entity_id: str | None = None
    version: int | None = None
    snapshot_id: str | None = None
    content_sha256: str | None = None
    policy_version: str | None = None
    reason: str | None = None


class AgentAuditRepository(Protocol):
    def append(self, event: AgentAuditEvent) -> None: ...

    def list_for_session(
        self, session_id: str, *, cursor: str | None, limit: int
    ) -> tuple[list[AgentAuditEvent], str | None]: ...

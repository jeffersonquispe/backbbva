from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class AuditEntry:
    actor_type: str
    actor_id: str
    worker_name: str | None
    action: str
    entity_type: str
    entity_id: str | None
    correlation_id: str
    parent_id: str | None
    occurred_at: datetime
    outcome: str


class AuditPort(Protocol):
    def write(self, entry: AuditEntry) -> None: ...

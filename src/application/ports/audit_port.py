from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol
from uuid import UUID


@dataclass
class AuditLogRecord:
    id: UUID
    organization_id: UUID
    user_id: Optional[UUID]
    conversation_id: Optional[UUID]
    tool_name: str
    arguments: str
    result_summary: Optional[str]
    latency_ms: Optional[int]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None


class AuditLogRepository(Protocol):
    def create(self, audit_log: AuditLogRecord) -> AuditLogRecord: ...

    def list_by_conversation(self, conversation_id: UUID) -> list[AuditLogRecord]: ...

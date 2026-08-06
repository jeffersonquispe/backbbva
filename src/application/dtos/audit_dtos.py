from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class CreateAuditLogInput:
    organization_id: UUID
    tool_name: str
    arguments: str                # JSON string
    user_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    result_summary: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    created_by: Optional[UUID] = None


@dataclass
class AuditLogOutput:
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

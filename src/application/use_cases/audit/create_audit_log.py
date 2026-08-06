from __future__ import annotations

import uuid
from datetime import datetime

from application.dtos.audit_dtos import CreateAuditLogInput, AuditLogOutput
from application.ports.audit_port import AuditLogRecord, AuditLogRepository


class CreateAuditLogUseCase:
    def __init__(self, audit_repo: AuditLogRepository) -> None:
        self._repo = audit_repo

    def execute(self, input: CreateAuditLogInput) -> AuditLogOutput:
        now = datetime.utcnow()
        log = AuditLogRecord(
            id=uuid.uuid4(),
            organization_id=input.organization_id,
            user_id=input.user_id,
            conversation_id=input.conversation_id,
            tool_name=input.tool_name,
            arguments=input.arguments,
            result_summary=input.result_summary,
            latency_ms=input.latency_ms,
            error=input.error,
            created_at=now,
            updated_at=now,
            created_by=input.created_by,
            updated_by=None,
        )
        saved = self._repo.create(log)
        return AuditLogOutput(
            id=saved.id,
            organization_id=saved.organization_id,
            user_id=saved.user_id,
            conversation_id=saved.conversation_id,
            tool_name=saved.tool_name,
            arguments=saved.arguments,
            result_summary=saved.result_summary,
            latency_ms=saved.latency_ms,
            error=saved.error,
            created_at=saved.created_at,
        )

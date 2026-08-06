from __future__ import annotations

from typing import List
from uuid import UUID

from application.dtos.audit_dtos import AuditLogOutput
from application.ports.audit_port import AuditLogRepository


class ListAuditLogsUseCase:
    def __init__(self, audit_repo: AuditLogRepository) -> None:
        self._repo = audit_repo

    def execute(self, conversation_id: UUID) -> List[AuditLogOutput]:
        logs = self._repo.list_by_conversation(conversation_id)
        return [
            AuditLogOutput(
                id=l.id,
                organization_id=l.organization_id,
                user_id=l.user_id,
                conversation_id=l.conversation_id,
                tool_name=l.tool_name,
                arguments=l.arguments,
                result_summary=l.result_summary,
                latency_ms=l.latency_ms,
                error=l.error,
                created_at=l.created_at,
            )
            for l in logs
        ]

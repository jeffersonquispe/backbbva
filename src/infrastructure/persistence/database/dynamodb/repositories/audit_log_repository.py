from __future__ import annotations

from uuid import uuid4

from src.application.ports.audit_port import AuditEntry, AuditPort
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "audit_log"


class DynamoAuditLogRepository(AuditPort):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def write(self, entry: AuditEntry) -> None:
        log_id = f"{entry.occurred_at.isoformat()}#{uuid4()}"
        item = {
            "partition": entry.occurred_at.date().isoformat(),
            "log_id": log_id,
            "tipo": entry.action,
            "actor_type": entry.actor_type,
            "actor_id": entry.actor_id,
            "worker_name": entry.worker_name,
            "accion": entry.action,
            "entidad_tipo": entry.entity_type,
            "entidad_id": entry.entity_id,
            "correlation_id": entry.correlation_id,
            "parent_id": entry.parent_id,
            "fecha": entry.occurred_at.isoformat(),
            "resultado": entry.outcome,
        }
        self._table.put_item(Item=item)

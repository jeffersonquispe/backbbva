from functools import lru_cache

from src.application.ports.audit_port import AuditPort
from src.infrastructure.persistence.database.dynamodb.repositories.audit_log_repository import (
    DynamoAuditLogRepository,
)


@lru_cache(maxsize=1)
def get_audit_repository() -> AuditPort:
    return DynamoAuditLogRepository()

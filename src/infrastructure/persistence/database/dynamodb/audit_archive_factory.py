from functools import lru_cache

from src.application.ports.audit_log_archive_port import AuditLogArchivePort
from src.application.use_cases.audit.flush_audit_log_archive import FlushAuditLogArchive
from src.application.use_cases.audit.query_audit_log import QueryAuditLog
from src.infrastructure.persistence.database.dynamodb.repositories.audit_log_archive_repository import (
    DynamoAuditLogArchiveRepository,
)
from src.infrastructure.persistence.object_storage.minio import get_object_storage


@lru_cache(maxsize=1)
def get_audit_log_archive_repository() -> AuditLogArchivePort:
    return DynamoAuditLogArchiveRepository(get_object_storage())


def get_flush_audit_log_archive_use_case() -> FlushAuditLogArchive:
    return FlushAuditLogArchive(get_audit_log_archive_repository())


def get_query_audit_log_use_case() -> QueryAuditLog:
    return QueryAuditLog(get_audit_log_archive_repository())

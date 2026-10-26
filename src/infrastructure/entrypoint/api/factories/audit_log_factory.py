from src.application.use_cases.audit.query_audit_log import QueryAuditLog
from src.infrastructure.persistence.database.dynamodb.audit_archive_factory import (
    get_query_audit_log_use_case as _get_query_audit_log_use_case,
)


def get_query_audit_log_use_case() -> QueryAuditLog:
    return _get_query_audit_log_use_case()

from __future__ import annotations

from datetime import date
from typing import Any

from src.application.ports.audit_log_archive_port import AuditLogArchivePort


class QueryAuditLog:
    def __init__(self, archive: AuditLogArchivePort) -> None:
        self._archive = archive

    def execute(
        self, *, from_date: date, to_date: date, limit: int = 1000
    ) -> list[dict[str, Any]]:
        if to_date < from_date:
            raise ValueError("to_date must be on or after from_date")
        if not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")
        return self._archive.query(
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            limit=limit,
        )

from __future__ import annotations

from src.application.ports.audit_log_archive_port import AuditLogArchivePort


class FlushAuditLogArchive:
    def __init__(self, archive: AuditLogArchivePort) -> None:
        self._archive = archive

    def execute(
        self, *, max_hot_items: int = 5000, retention_days: int = 5
    ) -> dict[str, int]:
        if max_hot_items < 1 or retention_days < 1:
            raise ValueError("Archive limits must be positive")
        return self._archive.flush(
            max_hot_items=max_hot_items, retention_days=retention_days
        )

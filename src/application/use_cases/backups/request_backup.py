from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from src.application.ports.backup_catalog_port import (
    BackupCatalogRepository,
    BackupRecord,
    BackupStatus,
)
from src.application.ports.backup_task_dispatcher_port import BackupTaskDispatcher


class RequestBackupUseCase:
    def __init__(
        self, repository: BackupCatalogRepository, dispatcher: BackupTaskDispatcher
    ) -> None:
        self._repository = repository
        self._dispatcher = dispatcher

    def execute(self, requested_by: str) -> BackupRecord:
        now = datetime.now(UTC)
        backup_id = str(uuid4())
        record = BackupRecord(
            backup_id=backup_id,
            directory=f"backups/{now.strftime('%Y%m%dT%H%M%SZ')}-{backup_id[:8]}",
            requested_by=requested_by,
            created_at=now,
            updated_at=now,
            status=BackupStatus.QUEUED,
        )
        record = self._repository.create(record)
        try:
            self._dispatcher.dispatch(backup_id)
        except Exception as exc:
            self._repository.update(
                replace(
                    record,
                    status=BackupStatus.FAILED,
                    updated_at=datetime.now(UTC),
                    error=str(exc),
                )
            )
            raise
        return record

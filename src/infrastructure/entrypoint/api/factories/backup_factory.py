from functools import lru_cache

from src.application.ports.backup_catalog_port import BackupCatalogRepository
from src.application.ports.backup_task_dispatcher_port import BackupTaskDispatcher
from src.application.use_cases.backups.list_backups import ListBackupsUseCase
from src.application.use_cases.backups.request_backup import RequestBackupUseCase
from src.infrastructure.persistence.database.dynamodb.repositories.backup_catalog_repository import (
    DynamoBackupCatalogRepository,
)
from src.infrastructure.queues.celery.backup_task_dispatcher import (
    CeleryBackupTaskDispatcher,
)


@lru_cache
def get_backup_catalog_repository() -> BackupCatalogRepository:
    return DynamoBackupCatalogRepository()


@lru_cache
def get_backup_task_dispatcher() -> BackupTaskDispatcher:
    return CeleryBackupTaskDispatcher()


def get_request_backup_use_case() -> RequestBackupUseCase:
    return RequestBackupUseCase(
        get_backup_catalog_repository(), get_backup_task_dispatcher()
    )


def get_list_backups_use_case() -> ListBackupsUseCase:
    return ListBackupsUseCase(get_backup_catalog_repository())

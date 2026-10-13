from src.application.ports.backup_catalog_port import (
    BackupCatalogRepository,
    BackupRecord,
)


class ListBackupsUseCase:
    def __init__(self, repository: BackupCatalogRepository) -> None:
        self._repository = repository

    def execute(self) -> list[BackupRecord]:
        return self._repository.list()

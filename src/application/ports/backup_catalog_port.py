from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class BackupStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class BackupRecord:
    backup_id: str
    directory: str
    requested_by: str
    created_at: datetime
    updated_at: datetime
    status: BackupStatus
    error: str | None = None
    dynamodb_items: int | None = None
    opensearch_documents: int | None = None
    object_storage_objects: int | None = None


class BackupCatalogRepository(Protocol):
    def create(self, record: BackupRecord) -> BackupRecord: ...

    def get(self, backup_id: str) -> BackupRecord | None: ...

    def update(self, record: BackupRecord) -> BackupRecord: ...

    def list(self) -> list[BackupRecord]: ...

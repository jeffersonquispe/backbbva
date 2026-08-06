from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class AsyncOperationStatus(StrEnum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass
class AsyncOperationRecord:
    id: UUID
    operation_type: str
    status: AsyncOperationStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    dispatched_at: datetime | None = None
    execution_backend: str | None = None
    external_id: str | None = None


class AsyncOperationRepository(Protocol):
    def create(
        self, operation: AsyncOperationRecord
    ) -> AsyncOperationRecord:
        ...

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        ...

    def list(
        self,
        status: AsyncOperationStatus | None = None,
        limit: int = 100,
    ) -> list[AsyncOperationRecord]:
        ...

    def update(
        self,
        operation_id: UUID,
        *,
        status: AsyncOperationStatus | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        dispatched_at: datetime | None = None,
        execution_backend: str | None = None,
        external_id: str | None = None,
    ) -> AsyncOperationRecord | None:
        ...

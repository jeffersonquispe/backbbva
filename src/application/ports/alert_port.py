from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class AlertStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


@dataclass
class AlertRecord:
    id: UUID
    event_id: str
    event_type: str
    payload: dict[str, Any]
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
    customer_id: str | None = None
    async_operation_id: UUID | None = None
    workflow_execution_id: UUID | None = None


class AlertRepository(Protocol):
    def create(self, alert: AlertRecord) -> AlertRecord:
        ...

    def get(self, alert_id: UUID) -> AlertRecord | None:
        ...

    def update(
        self,
        alert_id: UUID,
        *,
        status: AlertStatus | None = None,
        async_operation_id: UUID | None = None,
        workflow_execution_id: UUID | None = None,
    ) -> AlertRecord | None:
        ...

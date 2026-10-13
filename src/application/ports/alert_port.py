from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from src.domain.alerts.entities import (
    AlertRecord,
    AlertStatus,
)


class AlertRepository(Protocol):
    def create(self, alert: AlertRecord) -> AlertRecord: ...

    def get(self, alert_id: UUID) -> AlertRecord | None: ...

    def update(
        self,
        alert_id: UUID,
        *,
        status: AlertStatus | None = None,
        async_operation_id: UUID | None = None,
        workflow_execution_id: UUID | None = None,
        configuration_id: str | None = None,
        configuration_version: int | None = None,
        schema_version: int | None = None,
        input: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        history_prev_alerta: list[dict[str, Any]] | None = None,
        agent_output: dict[str, Any] | None = None,
        agent_output_ref: Any | None = None,
    ) -> AlertRecord | None: ...

    def delete(self, alert_id: UUID) -> None: ...

    def list_by_status(self, status: AlertStatus) -> list[AlertRecord]:
        """Oldest first - e.g. the ESCALATED alerts waiting in the analyst
        queue."""
        ...

    def count_by_status(self, status: AlertStatus) -> int:
        """How many alerts are in this status right now - the live funnel
        (R9). Served by a status index, never a Scan; may lag a status
        change by the index's propagation delay (sub-second)."""
        ...

    def list_by_created_day(self, created_day: date) -> list[AlertRecord]:
        """Alerts whose created_at falls on this calendar day in the
        operations timezone (Bogota), oldest first - served by an index,
        never a Scan (reconciliation, backfill, fraud history)."""
        ...

    def page_by_created_day(
        self, created_day: date, *, before: datetime | None, limit: int
    ) -> list[AlertRecord]:
        """Up to `limit` alerts of this operations-timezone day, NEWEST
        first, with created_at strictly before `before` (None = from the
        day's end) - the fraud history page reads a day in slices through
        the same index instead of loading the whole day."""
        ...

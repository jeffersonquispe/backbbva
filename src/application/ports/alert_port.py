from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class AlertStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    # Workflow finished by escalating to a human analyst - waits in the
    # analyst queue until someone takes and resolves it (then CLOSED).
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    # Not processed: the agent was switched off and the alert's origin is
    # one that must not run while it is off (see AlertOrigin).
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AlertOrigin(StrEnum):
    """Where an alert entered the pipeline. Decides what happens while the
    agent is switched off (OperationalSettings.agent_enabled = False):
    MANUAL and TEST_RUN still process, SIMULATOR and PRODUCTION are skipped."""

    MANUAL = "manual"
    TEST_RUN = "test_run"
    SIMULATOR = "simulator"
    PRODUCTION = "production"


PROCESSED_WHILE_AGENT_OFF = frozenset({AlertOrigin.MANUAL, AlertOrigin.TEST_RUN})


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

    def delete(self, alert_id: UUID) -> None:
        ...

    def list_by_status(self, status: AlertStatus) -> list[AlertRecord]:
        """Oldest first - e.g. the ESCALATED alerts waiting in the analyst
        queue."""
        ...

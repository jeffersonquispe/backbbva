from __future__ import annotations

from src.application.dtos.analyst_queue_dtos import InProcessAlertItem
from src.application.ports.alert_port import AlertRepository
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.domain.alerts.entities import AlertStatus

# The live funnel is small by design (alerts leave it within minutes); the
# cap only protects the endpoint from a backlog after an outage.
MAX_IN_PROCESS_ALERTS = 200


class ListInProcessAlertsUseCase:
    """Alerts ARIA is still working on (received or being processed) - not
    yet escalated, closed, skipped or failed - oldest first, each with the
    workflow step it is currently in."""

    def __init__(
        self,
        alert_repository: AlertRepository,
        workflow_repository: WorkflowExecutionRepository,
    ) -> None:
        self._alerts = alert_repository
        self._workflows = workflow_repository

    def execute(self) -> list[InProcessAlertItem]:
        alerts = sorted(
            [
                *self._alerts.list_by_status(AlertStatus.RECEIVED),
                *self._alerts.list_by_status(AlertStatus.PROCESSING),
            ],
            key=lambda alert: alert.created_at,
        )[:MAX_IN_PROCESS_ALERTS]
        items: list[InProcessAlertItem] = []
        for alert in alerts:
            workflow = (
                self._workflows.get(alert.workflow_execution_id)
                if alert.workflow_execution_id is not None
                else None
            )
            items.append(
                InProcessAlertItem(
                    alert=alert,
                    workflow_status=workflow.status.value if workflow else None,
                    current_step=workflow.current_step if workflow else None,
                )
            )
        return items

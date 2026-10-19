from __future__ import annotations

from uuid import UUID

from src.application.dtos.analyst_queue_dtos import AlertDetail
from src.application.ports.alert_port import AlertRepository
from src.application.ports.clock_port import Clock
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservationRepository,
)
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.ports.workflow_step_execution_port import (
    WorkflowStepExecutionRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.analyst_queue.analyst_reservations import (
    active_reservation_for_alert,
)
from src.domain.alerts.exceptions import AlertNotFoundError


class GetAlertDetailUseCase:
    """One alert with everything the analyst screen shows: its payload, who
    holds it, and every workflow step's input/output (the agent's
    reasoning, the playbook it followed, the executor's fallbacks)."""

    def __init__(
        self,
        alert_repository: AlertRepository,
        reservation_repository: ResourceReservationRepository,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
        clock: Clock | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._reservations = reservation_repository
        self._workflows = workflow_repository
        self._steps = step_repository
        self._clock = resolve_clock(clock)

    def execute(self, alert_id: UUID) -> AlertDetail:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise AlertNotFoundError(str(alert_id))
        workflow = (
            self._workflows.get(alert.workflow_execution_id)
            if alert.workflow_execution_id is not None
            else None
        )
        return AlertDetail(
            alert=alert,
            reservation=active_reservation_for_alert(
                self._reservations,
                ReservedResource.ANALYST,
                str(alert.id),
                self._clock.now(),
            ),
            workflow=workflow,
            steps=(
                self._steps.list_by_workflow(workflow.id)
                if workflow is not None
                else []
            ),
        )

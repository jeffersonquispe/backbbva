"""DynamoDB AlertLifecycleReader (R6): an alert's stored history for the
metrics backfill - its workflow execution (input origin/configuration_ref,
terminal status, output), the executor step's executed_action, and the
analyst resolution / voicebot callback recorded on its reservations."""
from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Attr

from src.application.ports.alert_lifecycle_port import (
    AlertLifecycleFacts,
    AlertLifecycleReader,
    HumanResolutionFacts,
    WorkflowOutcomeFacts,
)
from src.application.ports.alert_port import AlertRecord
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStatus,
    WorkflowStepExecutionRepository,
    WorkflowStepStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.repositories.resource_reservation_repository import (
    RESERVATIONS_TABLE_NAME,
    _from_item as reservation_from_item,
)

# release_reason values written by ResolveEscalatedAlertUseCase and
# CompleteVoicebotCallUseCase.
ANALYST_RESOLVED_REASON = "resolved"
VOICEBOT_CALLBACK_REASON = "callback"
_TERMINAL = frozenset({WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED})


class DynamoAlertLifecycleReader(AlertLifecycleReader):
    def __init__(
        self,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
    ) -> None:
        self._workflows = workflow_repository
        self._steps = step_repository
        self._reservations_table = get_dynamodb_resource().Table(RESERVATIONS_TABLE_NAME)
        # alert_id -> its resolving reservations. resource_reservations has
        # no alert index: built once per reader by ONE filtered Scan of
        # that (small, audit-only) table, only if some alert needs it.
        self._resolutions: dict[str, list[ResourceReservation]] | None = None

    def read(self, alert: AlertRecord) -> AlertLifecycleFacts:
        origin = configuration_id = None
        workflow_facts = None
        if alert.workflow_execution_id is not None:
            workflow = self._workflows.get(alert.workflow_execution_id)
            if workflow is not None:
                origin = workflow.input.get("origin")
                ref = workflow.input.get("configuration_ref") or {}
                configuration_id = ref.get("configuration_id") if isinstance(ref, dict) else None
                if workflow.status in _TERMINAL:
                    workflow_facts = WorkflowOutcomeFacts(
                        status=workflow.status.value,
                        finished_at=workflow.finished_at or workflow.updated_at,
                        output_status=(workflow.output or {}).get("status"),
                        executed_action=self._executed_action(workflow.id),
                    )
        resolutions = self._resolutions_for(str(alert.id))
        return AlertLifecycleFacts(
            origin=origin,
            configuration_id=configuration_id,
            workflow=workflow_facts,
            analyst_resolution=_latest(
                resolutions, ReservedResource.ANALYST, ANALYST_RESOLVED_REASON, "decision"
            ),
            voicebot_callback=_latest(
                resolutions, ReservedResource.VOICEBOT, VOICEBOT_CALLBACK_REASON, "outcome"
            ),
        )

    def _executed_action(self, workflow_id) -> str | None:
        executor_steps = [
            step
            for step in self._steps.list_by_workflow(workflow_id)
            if step.step_name == "executor"
            and step.status == WorkflowStepStatus.SUCCEEDED
            and step.output
        ]
        if not executor_steps:
            return None
        latest = max(executor_steps, key=lambda step: (step.attempt, step.created_at))
        action = latest.output.get("executed_action")
        return str(action) if action is not None else None

    def _resolutions_for(self, alert_id: str) -> list[ResourceReservation]:
        if self._resolutions is None:
            self._resolutions = {}
            kwargs: dict[str, Any] = {
                "FilterExpression": Attr("release_reason").is_in(
                    [ANALYST_RESOLVED_REASON, VOICEBOT_CALLBACK_REASON]
                )
            }
            while True:
                response = self._reservations_table.scan(**kwargs)
                for item in response.get("Items", []):
                    reservation = reservation_from_item(item)
                    self._resolutions.setdefault(reservation.alert_id, []).append(
                        reservation
                    )
                if "LastEvaluatedKey" not in response:
                    break
                kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return self._resolutions.get(alert_id, [])


def _latest(
    reservations: list[ResourceReservation],
    resource: ReservedResource,
    reason: str,
    detail_field: str,
) -> HumanResolutionFacts | None:
    matching = [
        r
        for r in reservations
        if r.resource == resource and r.release_reason == reason and r.released_at
    ]
    if not matching:
        return None
    latest = max(matching, key=lambda r: r.released_at)
    value = latest.detail.get(detail_field)
    value = str(value) if value is not None else None
    if detail_field == "decision":
        return HumanResolutionFacts(occurred_at=latest.released_at, decision=value)
    return HumanResolutionFacts(occurred_at=latest.released_at, outcome=value)

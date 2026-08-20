from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from src.application.dtos.alert_dtos import (
    StartAlertWorkflowInput,
    StartAlertWorkflowOutput,
)
from src.application.ports.alert_port import (
    AlertRecord,
    AlertRepository,
    AlertStatus,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.workflow_executor_port import WorkflowExecutor
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowExecutionRepository,
    WorkflowStatus,
)
from src.domain.alerts.exceptions import AlertPayloadTooLargeError

WORKFLOW_NAME = "massive_fraud_alert_review"

# DynamoDB hard-caps a single item at 400KB (409,600 bytes), covering
# attribute names + values together. Checked against a rough
# json.dumps(payload) byte count - not exact DynamoDB encoding, but close
# enough to fail fast with a clear error instead of a raw ValidationException
# out of put_item. The margin below 409,600 covers AlertRecord's other
# fields (id, event_id, event_type, status, timestamps, ...), which are
# small and roughly constant per alert.
MAX_ALERT_PAYLOAD_BYTES = 380_000


class StartAlertTestWorkflowUseCase:
    def __init__(
        self,
        alert_repository: AlertRepository,
        async_operation_repository: AsyncOperationRepository,
        workflow_repository: WorkflowExecutionRepository,
        workflow_executor: WorkflowExecutor,
    ) -> None:
        self._alert_repository = alert_repository
        self._async_operation_repository = async_operation_repository
        self._workflow_repository = workflow_repository
        self._workflow_executor = workflow_executor

    def execute(
        self,
        input: StartAlertWorkflowInput,
    ) -> StartAlertWorkflowOutput:
        payload_size = len(json.dumps(input.payload, default=str).encode("utf-8"))
        if payload_size > MAX_ALERT_PAYLOAD_BYTES:
            raise AlertPayloadTooLargeError(payload_size, MAX_ALERT_PAYLOAD_BYTES)
        now = datetime.now(timezone.utc)
        alert = self._alert_repository.create(
            AlertRecord(
                id=uuid.uuid4(),
                event_id=str(input.payload.get("eventId") or uuid.uuid4()),
                event_type=str(input.payload.get("eventType") or "unknown"),
                payload=input.payload,
                status=AlertStatus.RECEIVED,
                customer_id=_optional_str(input.payload.get("customerId")),
                created_at=now,
                updated_at=now,
            )
        )
        operation = self._async_operation_repository.create(
            AsyncOperationRecord(
                id=uuid.uuid4(),
                operation_type=f"workflow.{WORKFLOW_NAME}",
                status=AsyncOperationStatus.PENDING,
                payload={
                    "alert_id": str(alert.id),
                    "event_id": alert.event_id,
                    "event_type": alert.event_type,
                    "created_by": input.created_by,
                },
                result=None,
                error=None,
                created_at=now,
                updated_at=now,
                created_by=input.created_by,
            )
        )
        workflow = self._workflow_repository.create(
            WorkflowExecutionRecord(
                id=uuid.uuid4(),
                alert_id=alert.id,
                async_operation_id=operation.id,
                workflow_name=WORKFLOW_NAME,
                status=WorkflowStatus.PENDING,
                input={
                    "alert_payload": input.payload,
                    "config_overrides": input.config_overrides,
                },
                output=None,
                error=None,
                current_step=None,
                feedback_iterations=0,
                max_feedback_iterations=input.max_feedback_iterations,
                created_at=now,
                updated_at=now,
                test_run_id=input.test_run_id,
            )
        )
        execution_ref = self._workflow_executor.start(workflow)
        dispatched_at = datetime.now(timezone.utc)
        self._workflow_repository.update(
            workflow.id,
            status=WorkflowStatus.DISPATCHED,
            execution_backend=execution_ref.backend,
            external_id=execution_ref.external_id,
        )
        self._async_operation_repository.update(
            operation.id,
            status=AsyncOperationStatus.DISPATCHED,
            dispatched_at=dispatched_at,
            execution_backend=execution_ref.backend,
            external_id=execution_ref.external_id,
        )
        self._alert_repository.update(
            alert.id,
            status=AlertStatus.PROCESSING,
            async_operation_id=operation.id,
            workflow_execution_id=workflow.id,
        )
        return StartAlertWorkflowOutput(
            alert_id=alert.id,
            async_operation_id=operation.id,
            workflow_execution_id=workflow.id,
            status=WorkflowStatus.DISPATCHED.value,
        )


def _optional_str(value) -> str | None:
    if value is None:
        return None
    return str(value)

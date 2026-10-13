from __future__ import annotations

import dataclasses
import logging

from src.application.dtos.alert_dtos import (
    StartAlertWorkflowInput,
    StartAlertWorkflowOutput,
)
from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.ports.workflow_executor_port import WorkflowExecutor
from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.application.use_cases.alerts.raw_payload import RawAlertPayloadLoader
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.entities import (
    AlertRecord,
    AlertStatus,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)

WORKFLOW_NAME = "massive_fraud_alert_review"


class StartAlertTestWorkflowUseCase:
    def __init__(
        self,
        alert_repository: AlertRepository,
        async_operation_repository: AsyncOperationRepository,
        workflow_repository: WorkflowExecutionRepository,
        workflow_executor: WorkflowExecutor,
        metrics_recorder: RecordAlertMetricsEvent | None = None,
        object_storage: ObjectStoragePort | None = None,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._alert_repository = alert_repository
        self._async_operation_repository = async_operation_repository
        self._workflow_repository = workflow_repository
        self._workflow_executor = workflow_executor
        self._metrics = metrics_recorder
        self._raw_payloads = (
            RawAlertPayloadLoader(object_storage)
            if object_storage is not None
            else None
        )
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        input: StartAlertWorkflowInput,
    ) -> StartAlertWorkflowOutput:
        now = self._clock.now()
        alert_id = self._id_generator.new_id()
        raw_ref = (
            self._raw_payloads.store(str(alert_id), input.payload)
            if self._raw_payloads is not None
            else None
        )
        alert = self._alert_repository.create(
            AlertRecord(
                id=alert_id,
                event_id=str(
                    input.payload.get("eventId") or self._id_generator.new_id()
                ),
                event_type=str(input.payload.get("eventType") or "unknown"),
                status=AlertStatus.RECEIVED,
                customer_id=_optional_str(input.payload.get("customerId")),
                created_at=now,
                updated_at=now,
                raw_payload_ref=raw_ref,
            ),
            raw_payload=input.payload,
        )
        # Before dispatch, so the arrival snapshot normally lands before the
        # worker's first event (a race is still safe: snapshot_version).
        self._record_created(alert.id, input, now)
        operation = self._async_operation_repository.create(
            AsyncOperationRecord(
                id=self._id_generator.new_id(),
                operation_type=f"workflow.{WORKFLOW_NAME}",
                status=AsyncOperationStatus.PENDING,
                payload={
                    "alert_id": str(alert.id),
                    "event_id": alert.event_id,
                    "event_type": alert.event_type,
                    "created_by": input.created_by,
                    "origin": input.origin.value,
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
                id=self._id_generator.new_id(),
                alert_id=alert.id,
                async_operation_id=operation.id,
                workflow_name=WORKFLOW_NAME,
                status=WorkflowStatus.PENDING,
                input={
                    "raw_payload_ref": dataclasses.asdict(raw_ref) if raw_ref else None,
                    "test_labels": (
                        {"marcacion_final": input.payload.get("marcacion_final")}
                        if input.test_run_id is not None
                        and "marcacion_final" in input.payload
                        else {}
                    ),
                    "config_overrides": input.config_overrides,
                    "schema_version": input.schema_version,
                    "configuration_ref": (
                        dataclasses.asdict(input.configuration_ref)
                        if input.configuration_ref is not None
                        else None
                    ),
                    "origin": input.origin.value,
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
        dispatched_at = self._clock.now()
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

    def _record_created(self, alert_id, input: StartAlertWorkflowInput, now) -> None:
        # Best effort: never fail alert intake over metrics; a missed
        # arrival snapshot is rebuilt by the alert's next event or the
        # daily reconciliation.
        if self._metrics is None:
            return
        try:
            self._metrics.execute(
                RecordAlertMetricsEventInput(
                    alert_id=alert_id,
                    event_type=AlertMetricsEventType.CREATED,
                    occurred_at=now,
                    origin=input.origin.value,
                    configuration_id=(
                        input.configuration_ref.configuration_id
                        if input.configuration_ref is not None
                        else None
                    ),
                )
            )
        except Exception:
            logger.exception("Metrics event failed for alert %s", alert_id)


def _optional_str(value) -> str | None:
    if value is None:
        return None
    return str(value)

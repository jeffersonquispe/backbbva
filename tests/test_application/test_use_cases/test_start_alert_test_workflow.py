from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from src.application.dtos.alert_dtos import StartAlertWorkflowInput
from src.application.ports.alert_port import (
    AlertRecord,
    AlertStatus,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.ports.workflow_executor_port import (
    WorkflowExecutionRef,
    WorkflowExecutor,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
)
from src.application.use_cases.alerts.start_alert_test_workflow import (
    MAX_ALERT_PAYLOAD_BYTES,
    StartAlertTestWorkflowUseCase,
)
from src.domain.alerts.exceptions import AlertPayloadTooLargeError


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def update(
        self,
        alert_id: UUID,
        **changes: Any,
    ) -> AlertRecord | None:
        alert = self.alerts.get(alert_id)
        if alert is None:
            return None
        updated = AlertRecord(
            id=alert.id,
            event_id=alert.event_id,
            event_type=alert.event_type,
            payload=alert.payload,
            status=changes.get("status") or alert.status,
            customer_id=alert.customer_id,
            async_operation_id=changes.get("async_operation_id")
            or alert.async_operation_id,
            workflow_execution_id=changes.get("workflow_execution_id")
            or alert.workflow_execution_id,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )
        self.alerts[alert_id] = updated
        return updated


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {}

    def create(
        self,
        operation: AsyncOperationRecord,
    ) -> AsyncOperationRecord:
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        return self.operations.get(operation_id)

    def list(
        self,
        status: AsyncOperationStatus | None = None,
        limit: int = 100,
    ) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def update(
        self,
        operation_id: UUID,
        **changes: Any,
    ) -> AsyncOperationRecord | None:
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        updated = AsyncOperationRecord(
            id=operation.id,
            operation_type=operation.operation_type,
            status=changes.get("status") or operation.status,
            payload=operation.payload,
            result=operation.result,
            error=operation.error,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            created_by=operation.created_by,
            dispatched_at=changes.get("dispatched_at")
            or operation.dispatched_at,
            execution_backend=changes.get("execution_backend")
            or operation.execution_backend,
            external_id=changes.get("external_id") or operation.external_id,
        )
        self.operations[operation_id] = updated
        return updated


class InMemoryWorkflowExecutionRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, WorkflowExecutionRecord] = {}

    def create(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRecord:
        self.workflows[workflow.id] = workflow
        return workflow

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        return self.workflows.get(workflow_id)

    def update(
        self,
        workflow_id: UUID,
        **changes: Any,
    ) -> WorkflowExecutionRecord | None:
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return None
        updated = WorkflowExecutionRecord(
            id=workflow.id,
            alert_id=workflow.alert_id,
            async_operation_id=workflow.async_operation_id,
            workflow_name=workflow.workflow_name,
            status=changes.get("status") or workflow.status,
            input=workflow.input,
            output=changes.get("output") or workflow.output,
            error=changes.get("error") or workflow.error,
            current_step=changes.get("current_step")
            if "current_step" in changes
            else workflow.current_step,
            feedback_iterations=changes.get("feedback_iterations")
            if "feedback_iterations" in changes
            else workflow.feedback_iterations,
            max_feedback_iterations=workflow.max_feedback_iterations,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            finished_at=changes.get("finished_at") or workflow.finished_at,
            execution_backend=changes.get("execution_backend")
            or workflow.execution_backend,
            external_id=changes.get("external_id") or workflow.external_id,
        )
        self.workflows[workflow_id] = updated
        return updated


class RecordingWorkflowExecutor(WorkflowExecutor):
    def __init__(self) -> None:
        self.started: WorkflowExecutionRecord | None = None

    def start(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRef:
        self.started = workflow
        return WorkflowExecutionRef(backend="celery", external_id="task-123")


def test_start_alert_test_workflow_creates_tracking_records() -> None:
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    executor = RecordingWorkflowExecutor()
    use_case = StartAlertTestWorkflowUseCase(
        alert_repository=alerts,
        async_operation_repository=operations,
        workflow_repository=workflows,
        workflow_executor=executor,
    )

    output = use_case.execute(
        StartAlertWorkflowInput(
            payload={
                "eventId": "event-1",
                "eventType": "paymentRT",
                "customerId": "10264559",
            },
            created_by="tester",
        )
    )

    alert = alerts.get(output.alert_id)
    operation = operations.get(output.async_operation_id)
    workflow = workflows.get(output.workflow_execution_id)

    assert output.status == "DISPATCHED"
    assert alert.status == AlertStatus.PROCESSING
    assert alert.async_operation_id == operation.id
    assert alert.workflow_execution_id == workflow.id
    assert operation.status == AsyncOperationStatus.DISPATCHED
    assert operation.execution_backend == "celery"
    assert operation.external_id == "task-123"
    assert workflow.status == WorkflowStatus.DISPATCHED
    assert workflow.execution_backend == "celery"
    assert executor.started.id == workflow.id
    assert workflow.max_feedback_iterations == 1


def test_start_alert_test_workflow_honors_custom_max_feedback_iterations() -> None:
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    executor = RecordingWorkflowExecutor()
    use_case = StartAlertTestWorkflowUseCase(
        alert_repository=alerts,
        async_operation_repository=operations,
        workflow_repository=workflows,
        workflow_executor=executor,
    )

    output = use_case.execute(
        StartAlertWorkflowInput(
            payload={"eventId": "event-1"},
            max_feedback_iterations=5,
        )
    )

    assert workflows.get(output.workflow_execution_id).max_feedback_iterations == 5


def test_start_alert_test_workflow_rejects_oversized_payload_before_persisting() -> None:
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    executor = RecordingWorkflowExecutor()
    use_case = StartAlertTestWorkflowUseCase(
        alert_repository=alerts,
        async_operation_repository=operations,
        workflow_repository=workflows,
        workflow_executor=executor,
    )
    # A single oversized field (e.g. a customer's full transaction history
    # embedded as JSON in one dataset column) is enough to blow the budget.
    huge_payload = {"eventId": "event-1", "transacciones_json": "x" * (MAX_ALERT_PAYLOAD_BYTES + 1)}

    with pytest.raises(AlertPayloadTooLargeError):
        use_case.execute(StartAlertWorkflowInput(payload=huge_payload))

    # Nothing should have been persisted - this must fail before any writes,
    # not leave a half-created alert/operation/workflow behind.
    assert alerts.alerts == {}
    assert operations.operations == {}
    assert workflows.workflows == {}
    assert executor.started is None

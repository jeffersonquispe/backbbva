from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
    ReconcileAsyncOperationsOutput,
    ReconciledAsyncOperationOutput,
)
from src.application.ports.alert_port import AlertRepository
from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionInspector,
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.runtime_defaults import resolve_clock
from src.domain.alerts.entities import AlertStatus
from src.domain.workflows.entities import WorkflowStatus


class ReconcileAsyncOperationsUseCase:
    def __init__(
        self,
        repository: AsyncOperationRepository,
        inspector: AsyncExecutionInspector,
        workflow_repository: WorkflowExecutionRepository | None = None,
        alert_repository: AlertRepository | None = None,
        stuck_timeout_seconds: int = 900,
        queue_timeout_seconds: int = 3600,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository
        self._inspector = inspector
        self._workflows = workflow_repository
        self._alerts = alert_repository
        self._stuck_timeout = timedelta(seconds=stuck_timeout_seconds)
        self._queue_timeout = timedelta(seconds=queue_timeout_seconds)
        self._clock = resolve_clock(clock)

    def execute(
        self,
        input: ReconcileAsyncOperationsInput,
    ) -> ReconcileAsyncOperationsOutput:
        operations = self._repository.list_active(limit=input.limit)
        reconciled: list[ReconciledAsyncOperationOutput] = []

        for operation in operations:
            previous_status = operation.status
            snapshot = self._inspector.inspect(operation)
            stuck_error = self._stuck_error(operation, snapshot)
            if stuck_error is not None:
                updated = self._fail_stuck_operation(operation, stuck_error)
                snapshot = type(snapshot)(
                    state=AsyncExecutionState.FAILED,
                    detail=stuck_error,
                )
            else:
                updated = self._apply_snapshot(operation, snapshot)
            current_status = updated.status if updated else previous_status
            reconciled.append(
                ReconciledAsyncOperationOutput(
                    id=operation.id,
                    previous_status=previous_status,
                    current_status=current_status,
                    execution_state=snapshot.state,
                    detail=snapshot.detail,
                )
            )

        updated_count = sum(
            1 for item in reconciled if item.current_status != item.previous_status
        )
        return ReconcileAsyncOperationsOutput(
            inspected=len(reconciled),
            updated=updated_count,
            operations=reconciled,
        )

    def _stuck_error(self, operation, snapshot) -> str | None:
        # Waiting in the queue and running are timed separately: a long
        # backlog is not a hung task, and a running workflow is only stuck
        # once it stops reporting step progress.
        now = self._clock.now()
        dispatched_at = operation.dispatched_at or operation.created_at
        if snapshot.state == AsyncExecutionState.QUEUED:
            if now - dispatched_at >= self._queue_timeout:
                return "Execution exceeded the configured queue-wait timeout"
            return None
        if snapshot.state == AsyncExecutionState.RUNNING:
            if now - self._last_progress(operation, dispatched_at) >= (
                self._stuck_timeout
            ):
                return "Execution exceeded the configured stuck-task timeout"
        return None

    def _last_progress(self, operation, fallback):
        workflow_id = operation.payload.get("workflow_execution_id")
        if self._workflows is None or not workflow_id:
            return fallback
        try:
            workflow = self._workflows.get(UUID(str(workflow_id)))
        except ValueError:
            return fallback
        if workflow is None:
            return fallback
        return max(workflow.updated_at, fallback)

    def _fail_stuck_operation(self, operation: AsyncOperationRecord, error: str):
        updated = self._repository.update(
            operation.id, status=AsyncOperationStatus.FAILED, error=error
        )
        workflow_id = operation.payload.get("workflow_execution_id")
        if self._workflows is not None and workflow_id:
            try:
                self._workflows.update(
                    UUID(str(workflow_id)),
                    status=WorkflowStatus.FAILED,
                    error=error,
                    finished_at=self._clock.now(),
                )
            except ValueError:
                pass
        alert_id = operation.payload.get("alert_id")
        if self._alerts is not None and alert_id:
            try:
                self._alerts.update(UUID(str(alert_id)), status=AlertStatus.FAILED)
            except ValueError:
                pass
        return updated

    def _apply_snapshot(
        self,
        operation: AsyncOperationRecord,
        snapshot,
    ) -> AsyncOperationRecord | None:
        if snapshot.state == AsyncExecutionState.QUEUED:
            return self._repository.update(
                operation.id,
                status=AsyncOperationStatus.DISPATCHED,
            )
        if snapshot.state == AsyncExecutionState.RUNNING:
            return self._repository.update(
                operation.id,
                status=AsyncOperationStatus.RUNNING,
            )
        if snapshot.state == AsyncExecutionState.SUCCEEDED:
            return self._repository.update(
                operation.id,
                status=AsyncOperationStatus.SUCCEEDED,
                result=snapshot.result,
            )
        if snapshot.state == AsyncExecutionState.FAILED:
            return self._repository.update(
                operation.id,
                status=AsyncOperationStatus.FAILED,
                error=snapshot.detail or "Async execution failed",
            )
        return operation

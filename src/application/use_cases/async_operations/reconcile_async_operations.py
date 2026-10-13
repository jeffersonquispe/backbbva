from __future__ import annotations

from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
    ReconcileAsyncOperationsOutput,
    ReconciledAsyncOperationOutput,
)
from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionInspector,
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)


class ReconcileAsyncOperationsUseCase:
    def __init__(
        self,
        repository: AsyncOperationRepository,
        inspector: AsyncExecutionInspector,
    ) -> None:
        self._repository = repository
        self._inspector = inspector

    def execute(
        self,
        input: ReconcileAsyncOperationsInput,
    ) -> ReconcileAsyncOperationsOutput:
        operations = self._repository.list_active(limit=input.limit)
        reconciled: list[ReconciledAsyncOperationOutput] = []

        for operation in operations:
            previous_status = operation.status
            snapshot = self._inspector.inspect(operation)
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

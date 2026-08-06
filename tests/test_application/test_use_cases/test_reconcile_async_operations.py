from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
)
from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionInspector,
    AsyncExecutionSnapshot,
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.use_cases.async_operations.reconcile_async_operations import (
    ReconcileAsyncOperationsUseCase,
)


class InMemoryAsyncOperationRepository:
    def __init__(self, operations: list[AsyncOperationRecord]) -> None:
        self.operations = {operation.id: operation for operation in operations}

    def create(
        self, operation: AsyncOperationRecord
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
        items = list(self.operations.values())
        if status is not None:
            items = [item for item in items if item.status == status]
        return items[:limit]

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        return [
            operation
            for operation in self.operations.values()
            if operation.status
            in {
                AsyncOperationStatus.PENDING,
                AsyncOperationStatus.DISPATCHED,
                AsyncOperationStatus.RUNNING,
            }
        ][:limit]

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
            result=changes.get("result") or operation.result,
            error=changes.get("error") or operation.error,
            created_at=operation.created_at,
            updated_at=datetime.now(timezone.utc),
            created_by=operation.created_by,
            dispatched_at=operation.dispatched_at,
            execution_backend=operation.execution_backend,
            external_id=operation.external_id,
        )
        self.operations[operation_id] = updated
        return updated


class StaticInspector(AsyncExecutionInspector):
    def __init__(self, snapshot: AsyncExecutionSnapshot) -> None:
        self._snapshot = snapshot

    def inspect(
        self,
        operation: AsyncOperationRecord,
    ) -> AsyncExecutionSnapshot:
        return self._snapshot


def _operation(status: AsyncOperationStatus) -> AsyncOperationRecord:
    now = datetime.now(timezone.utc)
    return AsyncOperationRecord(
        id=uuid4(),
        operation_type="fraud.massive-review",
        status=status,
        payload={},
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
        execution_backend="celery",
        external_id="task-123",
    )


def test_reconcile_marks_succeeded_from_backend_state() -> None:
    operation = _operation(AsyncOperationStatus.DISPATCHED)
    repository = InMemoryAsyncOperationRepository([operation])
    use_case = ReconcileAsyncOperationsUseCase(
        repository,
        StaticInspector(
            AsyncExecutionSnapshot(
                state=AsyncExecutionState.SUCCEEDED,
                result={"ok": True},
            )
        ),
    )

    output = use_case.execute(ReconcileAsyncOperationsInput(limit=10))

    assert output.inspected == 1
    assert output.updated == 1
    saved = repository.get(operation.id)
    assert saved.status == AsyncOperationStatus.SUCCEEDED
    assert saved.result == {"ok": True}


def test_reconcile_marks_failed_from_backend_state() -> None:
    operation = _operation(AsyncOperationStatus.RUNNING)
    repository = InMemoryAsyncOperationRepository([operation])
    use_case = ReconcileAsyncOperationsUseCase(
        repository,
        StaticInspector(
            AsyncExecutionSnapshot(
                state=AsyncExecutionState.FAILED,
                detail="worker crashed",
            )
        ),
    )

    use_case.execute(ReconcileAsyncOperationsInput(limit=10))

    saved = repository.get(operation.id)
    assert saved.status == AsyncOperationStatus.FAILED
    assert saved.error == "worker crashed"


def test_reconcile_keeps_status_when_backend_state_unknown() -> None:
    operation = _operation(AsyncOperationStatus.DISPATCHED)
    repository = InMemoryAsyncOperationRepository([operation])
    use_case = ReconcileAsyncOperationsUseCase(
        repository,
        StaticInspector(
            AsyncExecutionSnapshot(
                state=AsyncExecutionState.UNKNOWN,
                detail="missing backend metadata",
            )
        ),
    )

    output = use_case.execute(ReconcileAsyncOperationsInput(limit=10))

    assert output.updated == 0
    assert repository.get(operation.id).status == AsyncOperationStatus.DISPATCHED
    assert output.operations[0].detail == "missing backend metadata"

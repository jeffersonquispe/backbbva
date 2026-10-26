from datetime import UTC, datetime
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from src.application.dtos.async_reconciliation_dtos import ReconcileAsyncOperationsInput
from src.application.ports.async_execution_inspector_port import (
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
    def __init__(self, operation: AsyncOperationRecord) -> None:
        self.operation = operation

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        if self.operation.status in {
            AsyncOperationStatus.PENDING,
            AsyncOperationStatus.DISPATCHED,
            AsyncOperationStatus.RUNNING,
        }:
            return [self.operation][:limit]
        return []

    def update(self, operation_id, **changes):
        if operation_id != self.operation.id:
            return None
        self.operation = AsyncOperationRecord(
            id=self.operation.id,
            operation_type=self.operation.operation_type,
            status=changes.get("status", self.operation.status),
            payload=self.operation.payload,
            result=changes.get("result", self.operation.result),
            error=changes.get("error", self.operation.error),
            created_at=self.operation.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.operation.created_by,
            dispatched_at=self.operation.dispatched_at,
            execution_backend=self.operation.execution_backend,
            external_id=self.operation.external_id,
        )
        return self.operation


class StaticInspector:
    def __init__(self, snapshot: AsyncExecutionSnapshot) -> None:
        self.snapshot = snapshot

    def inspect(self, operation: AsyncOperationRecord) -> AsyncExecutionSnapshot:
        return self.snapshot


def _operation() -> AsyncOperationRecord:
    now = datetime.now(UTC)
    return AsyncOperationRecord(
        id=uuid4(),
        operation_type="alert.review",
        status=AsyncOperationStatus.DISPATCHED,
        payload={},
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
        execution_backend="celery",
        external_id="celery-task",
    )


RESULTS = st.dictionaries(
    keys=st.text(min_size=1, max_size=12),
    values=st.one_of(st.text(max_size=20), st.integers(), st.booleans(), st.none()),
    max_size=6,
)


@given(result=RESULTS)
def test_successful_reconciliation_preserves_result_and_is_retry_safe(result) -> None:
    operation = _operation()
    repository = InMemoryAsyncOperationRepository(operation)
    use_case = ReconcileAsyncOperationsUseCase(
        repository,
        StaticInspector(
            AsyncExecutionSnapshot(state=AsyncExecutionState.SUCCEEDED, result=result)
        ),
    )

    first = use_case.execute(ReconcileAsyncOperationsInput(limit=10))
    second = use_case.execute(ReconcileAsyncOperationsInput(limit=10))

    assert first.updated == 1
    assert repository.operation.status is AsyncOperationStatus.SUCCEEDED
    assert repository.operation.result == result
    assert second.inspected == 0
    assert repository.operation.result == result

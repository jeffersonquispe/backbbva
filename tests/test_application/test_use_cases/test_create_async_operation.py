from __future__ import annotations

from typing import Any
from uuid import UUID

from src.application.dtos.async_operation_dtos import (
    CreateAsyncOperationInput,
)
from src.application.ports.async_executor_port import (
    AsyncExecutionRef,
    AsyncExecutor,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.use_cases.async_operations.create_async_operation import (
    CreateAsyncOperationUseCase,
)


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {}

    def create(self, operation: AsyncOperationRecord) -> AsyncOperationRecord:
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
            updated_at=operation.updated_at,
            created_by=operation.created_by,
            dispatched_at=(changes.get("dispatched_at") or operation.dispatched_at),
            execution_backend=(
                changes.get("execution_backend") or operation.execution_backend
            ),
            external_id=changes.get("external_id") or operation.external_id,
        )
        self.operations[operation_id] = updated
        return updated


class SuccessfulExecutor(AsyncExecutor):
    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        return AsyncExecutionRef(backend="celery", external_id="task-123")


class FailingExecutor(AsyncExecutor):
    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        raise RuntimeError("broker unavailable")


def test_create_async_operation_dispatches_and_tracks_executor_ref() -> None:
    repository = InMemoryAsyncOperationRepository()
    use_case = CreateAsyncOperationUseCase(repository, SuccessfulExecutor())

    output = use_case.execute(
        CreateAsyncOperationInput(
            operation_type="fraud.massive-review",
            payload={"case_id": "case-1"},
            created_by="tester",
        )
    )

    assert output.status == AsyncOperationStatus.DISPATCHED
    assert output.execution_backend == "celery"
    assert output.external_id == "task-123"
    assert output.dispatched_at is not None
    assert repository.get(output.id).status == AsyncOperationStatus.DISPATCHED


def test_create_async_operation_marks_failed_when_dispatch_fails() -> None:
    repository = InMemoryAsyncOperationRepository()
    use_case = CreateAsyncOperationUseCase(repository, FailingExecutor())

    output = use_case.execute(
        CreateAsyncOperationInput(
            operation_type="fraud.massive-review",
            payload={"case_id": "case-1"},
        )
    )

    assert output.status == AsyncOperationStatus.FAILED
    assert output.error == "broker unavailable"
    assert repository.get(output.id).status == AsyncOperationStatus.FAILED


def test_create_async_operation_rejects_unsupported_type_without_side_effects() -> None:
    import pytest

    from src.application.use_cases.async_operations.create_async_operation import (
        UnsupportedAsyncOperationTypeError,
    )

    class CountingExecutor(SuccessfulExecutor):
        calls = 0

        def dispatch(self, operation):
            CountingExecutor.calls += 1
            return super().dispatch(operation)

    repository = InMemoryAsyncOperationRepository()
    use_case = CreateAsyncOperationUseCase(
        repository, CountingExecutor(), supported_operation_types=frozenset()
    )

    with pytest.raises(UnsupportedAsyncOperationTypeError):
        use_case.execute(
            CreateAsyncOperationInput(operation_type="fraud.massive-review", payload={})
        )

    assert repository.operations == {}
    assert CountingExecutor.calls == 0


def test_create_async_operation_accepts_registered_type() -> None:
    repository = InMemoryAsyncOperationRepository()
    use_case = CreateAsyncOperationUseCase(
        repository,
        SuccessfulExecutor(),
        supported_operation_types=frozenset({"fraud.massive-review"}),
    )

    output = use_case.execute(
        CreateAsyncOperationInput(operation_type="fraud.massive-review", payload={})
    )

    assert output.status == AsyncOperationStatus.DISPATCHED

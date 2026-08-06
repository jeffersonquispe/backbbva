from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.dtos.async_operation_dtos import (
    AsyncOperationOutput,
    CreateAsyncOperationInput,
)
from src.application.ports.async_executor_port import AsyncExecutor
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)


class CreateAsyncOperationUseCase:
    def __init__(
        self,
        repository: AsyncOperationRepository,
        executor: AsyncExecutor,
    ) -> None:
        self._repository = repository
        self._executor = executor

    def execute(
        self, input: CreateAsyncOperationInput
    ) -> AsyncOperationOutput:
        now = datetime.now(timezone.utc)
        operation = AsyncOperationRecord(
            id=uuid.uuid4(),
            operation_type=input.operation_type,
            status=AsyncOperationStatus.PENDING,
            payload=input.payload,
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
            created_by=input.created_by,
        )
        saved = self._repository.create(operation)
        try:
            execution_ref = self._executor.dispatch(saved)
        except Exception as exc:
            failed = self._repository.update(
                saved.id,
                status=AsyncOperationStatus.FAILED,
                error=str(exc),
            )
            return _to_output(failed or saved)

        dispatched = self._repository.update(
            saved.id,
            status=AsyncOperationStatus.DISPATCHED,
            dispatched_at=datetime.now(timezone.utc),
            execution_backend=execution_ref.backend,
            external_id=execution_ref.external_id,
        )
        return _to_output(dispatched or saved)


def _to_output(operation: AsyncOperationRecord) -> AsyncOperationOutput:
    return AsyncOperationOutput(
        id=operation.id,
        operation_type=operation.operation_type,
        status=operation.status,
        payload=operation.payload,
        result=operation.result,
        error=operation.error,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        created_by=operation.created_by,
        dispatched_at=operation.dispatched_at,
        execution_backend=operation.execution_backend,
        external_id=operation.external_id,
    )

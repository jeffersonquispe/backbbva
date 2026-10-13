from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.dtos.async_operation_dtos import (
    AsyncOperationOutput,
    CreateAsyncOperationInput,
)
from src.application.errors import ValidationError
from src.application.ports.async_executor_port import AsyncExecutor
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)

# operation_type values the generic ``POST /async-operations`` path can run.
# Empty on purpose: every real operation (datasets, models, workflows) creates
# its own record and dispatches its own task. Register a handler for a type in
# the worker's ``run_async_operation`` and add it here before accepting it.
GENERIC_OPERATION_TYPES: frozenset[str] = frozenset()


class UnsupportedAsyncOperationTypeError(ValidationError):
    def __init__(self, operation_type: str) -> None:
        super().__init__(f"Unsupported async operation type: {operation_type}")
        self.operation_type = operation_type


class CreateAsyncOperationUseCase:
    def __init__(
        self,
        repository: AsyncOperationRepository,
        executor: AsyncExecutor,
        supported_operation_types: frozenset[str] | None = None,
    ) -> None:
        """``supported_operation_types=None`` accepts any type (no gate)."""
        self._repository = repository
        self._executor = executor
        self._supported = supported_operation_types

    def execute(self, input: CreateAsyncOperationInput) -> AsyncOperationOutput:
        if self._supported is not None and input.operation_type not in self._supported:
            raise UnsupportedAsyncOperationTypeError(input.operation_type)
        now = datetime.now(UTC)
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
        except Exception as exc:  # noqa: BLE001 - persist any dispatch failure
            failed = self._repository.update(
                saved.id,
                status=AsyncOperationStatus.FAILED,
                error=str(exc),
            )
            return _to_output(failed or saved)

        dispatched = self._repository.update(
            saved.id,
            status=AsyncOperationStatus.DISPATCHED,
            dispatched_at=datetime.now(UTC),
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

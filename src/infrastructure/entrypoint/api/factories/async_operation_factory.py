from __future__ import annotations

from functools import lru_cache

from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionInspector,
    AsyncExecutionSnapshot,
    AsyncExecutionState,
)
from src.application.ports.async_executor_port import (
    AsyncExecutionRef,
    AsyncExecutor,
)
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.application.use_cases.async_operations.create_async_operation import (
    GENERIC_OPERATION_TYPES,
    CreateAsyncOperationUseCase,
)
from src.application.use_cases.async_operations.get_async_operation import (
    GetAsyncOperationUseCase,
)
from src.application.use_cases.async_operations.list_async_operations import (
    ListAsyncOperationsUseCase,
)
from src.application.use_cases.async_operations.reconcile_async_operations import (
    ReconcileAsyncOperationsUseCase,
)
from src.application.use_cases.async_operations.update_async_operation import (
    UpdateAsyncOperationUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)


class DeferredAsyncExecutor(AsyncExecutor):
    """Local no-op executor for environments without an async backend."""

    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        return AsyncExecutionRef(backend="deferred")


class DeferredAsyncExecutionInspector(AsyncExecutionInspector):
    def inspect(
        self,
        operation: AsyncOperationRecord,
    ) -> AsyncExecutionSnapshot:
        return AsyncExecutionSnapshot(
            state=AsyncExecutionState.UNKNOWN,
            detail="Deferred executor has no backend state",
        )


@lru_cache
def get_async_operation_repository() -> DynamoAsyncOperationRepository:
    return DynamoAsyncOperationRepository()


@lru_cache
def get_async_executor() -> AsyncExecutor:
    backend = genai_config.ASYNC_EXECUTOR_BACKEND.strip().lower()
    if backend == "celery":
        from src.infrastructure.queues.celery.dispatcher import (
            CeleryAsyncExecutor,
        )

        return CeleryAsyncExecutor()
    if backend == "deferred":
        return DeferredAsyncExecutor()

    raise ValueError(f"Unsupported async executor backend: {backend}")


@lru_cache
def get_async_execution_inspector() -> AsyncExecutionInspector:
    backend = genai_config.ASYNC_EXECUTOR_BACKEND.strip().lower()
    if backend == "celery":
        from src.infrastructure.queues.celery.inspector import (
            CeleryAsyncExecutionInspector,
        )

        return CeleryAsyncExecutionInspector()
    if backend == "deferred":
        return DeferredAsyncExecutionInspector()

    raise ValueError(f"Unsupported async executor backend: {backend}")


def get_create_async_operation_use_case() -> CreateAsyncOperationUseCase:
    return CreateAsyncOperationUseCase(
        repository=get_async_operation_repository(),
        executor=get_async_executor(),
        supported_operation_types=GENERIC_OPERATION_TYPES,
    )


def get_get_async_operation_use_case() -> GetAsyncOperationUseCase:
    return GetAsyncOperationUseCase(get_async_operation_repository())


def get_list_async_operations_use_case() -> ListAsyncOperationsUseCase:
    return ListAsyncOperationsUseCase(get_async_operation_repository())


def get_update_async_operation_use_case() -> UpdateAsyncOperationUseCase:
    return UpdateAsyncOperationUseCase(get_async_operation_repository())


def get_reconcile_async_operations_use_case() -> ReconcileAsyncOperationsUseCase:
    return ReconcileAsyncOperationsUseCase(
        repository=get_async_operation_repository(),
        inspector=get_async_execution_inspector(),
    )

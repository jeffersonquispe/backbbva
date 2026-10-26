from __future__ import annotations

from functools import lru_cache

from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.use_cases.async_operations.get_async_operation import (
    GetAsyncOperationUseCase,
)
from src.application.use_cases.async_operations.list_async_operations import (
    ListAsyncOperationsUseCase,
)
from src.application.use_cases.async_operations.update_async_operation import (
    UpdateAsyncOperationUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)


@lru_cache
def get_async_operation_repository() -> AsyncOperationRepository:
    return DynamoAsyncOperationRepository()


def get_get_async_operation_use_case() -> GetAsyncOperationUseCase:
    return GetAsyncOperationUseCase(get_async_operation_repository())


def get_list_async_operations_use_case() -> ListAsyncOperationsUseCase:
    return ListAsyncOperationsUseCase(get_async_operation_repository())


def get_update_async_operation_use_case() -> UpdateAsyncOperationUseCase:
    return UpdateAsyncOperationUseCase(get_async_operation_repository())

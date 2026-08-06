from __future__ import annotations

from src.application.dtos.async_operation_dtos import AsyncOperationOutput
from src.application.ports.async_operation_port import (
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.use_cases.async_operations.create_async_operation import (
    _to_output,
)


class ListAsyncOperationsUseCase:
    def __init__(self, repository: AsyncOperationRepository) -> None:
        self._repository = repository

    def execute(
        self,
        status: AsyncOperationStatus | None = None,
        limit: int = 100,
    ) -> list[AsyncOperationOutput]:
        return [
            _to_output(operation)
            for operation in self._repository.list(status=status, limit=limit)
        ]

from __future__ import annotations

from uuid import UUID

from src.application.dtos.async_operation_dtos import AsyncOperationOutput
from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.use_cases.async_operations.create_async_operation import (
    _to_output,
)


class GetAsyncOperationUseCase:
    def __init__(self, repository: AsyncOperationRepository) -> None:
        self._repository = repository

    def execute(self, operation_id: UUID) -> AsyncOperationOutput | None:
        operation = self._repository.get(operation_id)
        if operation is None:
            return None
        return _to_output(operation)

from __future__ import annotations

from src.application.ports.async_executor_port import (
    AsyncExecutionRef,
    AsyncExecutor,
)
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.infrastructure.queues.celery.tasks import run_async_operation


class CeleryAsyncExecutor(AsyncExecutor):
    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        result = run_async_operation.delay(str(operation.id))
        return AsyncExecutionRef(
            backend="celery",
            external_id=result.id,
        )

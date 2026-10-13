from __future__ import annotations

from src.application.ports.async_executor_port import (
    AsyncExecutionRef,
    AsyncExecutor,
)
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.infrastructure.queues.celery.app import app

_TASK_NAME = "async_operations.run"


class CeleryAsyncExecutor(AsyncExecutor):
    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        result = app.send_task(_TASK_NAME, args=[str(operation.id)])
        return AsyncExecutionRef(
            backend="celery",
            external_id=result.id,
        )

from __future__ import annotations

from src.application.ports.async_executor_port import AsyncExecutionRef, AsyncExecutor
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.infrastructure.queues.celery.app import app as celery_app


class CeleryMatureSampleExecutor(AsyncExecutor):
    """Dispatches one mature snapshot build to the regular worker queue."""

    def dispatch(self, operation: AsyncOperationRecord) -> AsyncExecutionRef:
        result = celery_app.send_task(
            "datasets.sample_mature",
            args=[str(operation.id)],
        )
        return AsyncExecutionRef(backend="celery", external_id=result.id)

from __future__ import annotations

from uuid import UUID

from src.application.ports.async_operation_port import AsyncOperationStatus
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.queues.celery.celery_app import app


@app.task(name="queue.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "backend": "celery"}


@app.task(name="async_operations.run")
def run_async_operation(operation_id: str) -> dict[str, str]:
    repository = DynamoAsyncOperationRepository()
    operation_uuid = UUID(operation_id)

    operation = repository.update(
        operation_uuid,
        status=AsyncOperationStatus.RUNNING,
    )
    if operation is None:
        return {"status": "not_found", "operation_id": operation_id}

    repository.update(
        operation_uuid,
        status=AsyncOperationStatus.SUCCEEDED,
        result={
            "message": "Async operation executed by celery worker",
            "operation_type": operation.operation_type,
        },
    )
    return {"status": "ok", "operation_id": operation_id}

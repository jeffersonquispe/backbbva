from __future__ import annotations

from uuid import UUID

from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
)
from src.application.use_cases.async_operations.reconcile_async_operations import (
    ReconcileAsyncOperationsUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.queues.celery.celery_app import app
from src.infrastructure.queues.celery.inspector import (
    CeleryAsyncExecutionInspector,
)


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


@app.task(name="async_operations.reconcile")
def reconcile_async_operations(limit: int = 100) -> dict:
    use_case = ReconcileAsyncOperationsUseCase(
        repository=DynamoAsyncOperationRepository(),
        inspector=CeleryAsyncExecutionInspector(),
    )
    output = use_case.execute(ReconcileAsyncOperationsInput(limit=limit))
    return {
        "inspected": output.inspected,
        "updated": output.updated,
        "operations": [
            {
                "id": str(operation.id),
                "previous_status": operation.previous_status.value,
                "current_status": operation.current_status.value,
                "execution_state": operation.execution_state.value,
                "detail": operation.detail,
            }
            for operation in output.operations
        ],
    }

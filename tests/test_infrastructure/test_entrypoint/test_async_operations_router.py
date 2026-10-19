from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.async_operation_dtos import AsyncOperationOutput
from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
    ReconcileAsyncOperationsOutput,
    ReconciledAsyncOperationOutput,
)
from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_get_async_operation_use_case,
    get_reconcile_async_operations_use_case,
)
from src.infrastructure.entrypoint.api.routers.async_operations_router import (
    router,
)


class InMemoryGetAsyncOperationUseCase:
    def __init__(self, operation: AsyncOperationOutput | None) -> None:
        self._operation = operation

    def execute(self, operation_id: UUID) -> AsyncOperationOutput | None:
        return self._operation


class InMemoryReconcileAsyncOperationsUseCase:
    def execute(
        self,
        input: ReconcileAsyncOperationsInput,
    ) -> ReconcileAsyncOperationsOutput:
        return ReconcileAsyncOperationsOutput(
            inspected=input.limit,
            updated=1,
            operations=[
                ReconciledAsyncOperationOutput(
                    id=uuid4(),
                    previous_status=AsyncOperationStatus.RUNNING,
                    current_status=AsyncOperationStatus.SUCCEEDED,
                    execution_state=AsyncExecutionState.SUCCEEDED,
                    detail=None,
                )
            ],
        )


def _client(operation: AsyncOperationOutput | None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_get_async_operation_use_case] = (
        lambda: InMemoryGetAsyncOperationUseCase(operation)
    )
    app.dependency_overrides[get_reconcile_async_operations_use_case] = (
        lambda: InMemoryReconcileAsyncOperationsUseCase()
    )
    return TestClient(app)


def _operation(status: AsyncOperationStatus) -> AsyncOperationOutput:
    now = datetime.now(UTC)
    return AsyncOperationOutput(
        id=uuid4(),
        operation_type="fraud.massive-review",
        status=status,
        payload={"case_id": "case-1"},
        result={"ok": True} if status == AsyncOperationStatus.SUCCEEDED else None,
        error="failed" if status == AsyncOperationStatus.FAILED else None,
        created_at=now,
        updated_at=now,
        created_by="tester",
        dispatched_at=now,
        execution_backend="celery",
        external_id="task-123",
    )


def test_poll_async_operation_returns_retry_hint_when_not_done() -> None:
    operation = _operation(AsyncOperationStatus.RUNNING)
    response = _client(operation).get(f"/async-operations/{operation.id}/poll")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(operation.id)
    assert body["status"] == "RUNNING"
    assert body["done"] is False
    assert body["retry_after_seconds"] == 2


def test_poll_async_operation_returns_done_when_terminal() -> None:
    operation = _operation(AsyncOperationStatus.SUCCEEDED)
    response = _client(operation).get(f"/async-operations/{operation.id}/poll")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["done"] is True
    assert body["retry_after_seconds"] is None
    assert body["result"] == {"ok": True}


def test_poll_async_operation_returns_404_when_missing() -> None:
    response = _client(None).get(f"/async-operations/{uuid4()}/poll")

    assert response.status_code == 404


def test_reconcile_async_operations_returns_summary() -> None:
    response = _client(None).post(
        "/async-operations/reconcile",
        json={"limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["inspected"] == 5
    assert body["updated"] == 1
    assert body["operations"][0]["previous_status"] == "RUNNING"
    assert body["operations"][0]["current_status"] == "SUCCEEDED"
    assert body["operations"][0]["execution_state"] == "SUCCEEDED"


def test_create_async_operation_returns_422_for_unsupported_type() -> None:
    from src.application.use_cases.async_operations.create_async_operation import (
        UnsupportedAsyncOperationTypeError,
    )
    from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
        get_create_async_operation_use_case,
    )

    class RejectingUseCase:
        def execute(self, input):
            raise UnsupportedAsyncOperationTypeError(input.operation_type)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_create_async_operation_use_case] = (
        lambda: RejectingUseCase()
    )

    response = TestClient(app).post(
        "/async-operations",
        json={"operation_type": "fraud.massive-review", "payload": {}},
    )

    assert response.status_code == 422
    assert "fraud.massive-review" in response.json()["detail"]

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.dtos.async_operation_dtos import (
    CreateAsyncOperationInput,
    UpdateAsyncOperationInput,
)
from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.use_cases.async_operations.create_async_operation import (
    CreateAsyncOperationUseCase,
    UnsupportedAsyncOperationTypeError,
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
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_create_async_operation_use_case,
    get_get_async_operation_use_case,
    get_list_async_operations_use_case,
    get_reconcile_async_operations_use_case,
    get_update_async_operation_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    AsyncOperationPollingResponse,
    AsyncOperationResponse,
    CreateAsyncOperationRequest,
    ReconcileAsyncOperationsRequest,
    ReconcileAsyncOperationsResponse,
    UpdateAsyncOperationRequest,
)

router = APIRouter(prefix="/async-operations", tags=["async-operations"])
TERMINAL_STATUSES = {
    AsyncOperationStatus.SUCCEEDED,
    AsyncOperationStatus.FAILED,
}


@router.post(
    "",
    response_model=AsyncOperationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_async_operation(
    request: CreateAsyncOperationRequest,
    use_case: Annotated[
        CreateAsyncOperationUseCase,
        Depends(get_create_async_operation_use_case),
    ],
):
    try:
        return use_case.execute(
            CreateAsyncOperationInput(
                operation_type=request.operation_type,
                payload=request.payload,
                created_by=request.created_by,
            )
        )
    except UnsupportedAsyncOperationTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=list[AsyncOperationResponse])
def list_async_operations(
    use_case: Annotated[
        ListAsyncOperationsUseCase,
        Depends(get_list_async_operations_use_case),
    ],
    operation_status: Annotated[
        AsyncOperationStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return use_case.execute(status=operation_status, limit=limit)


@router.post("/reconcile", response_model=ReconcileAsyncOperationsResponse)
def reconcile_async_operations(
    request: ReconcileAsyncOperationsRequest,
    use_case: Annotated[
        ReconcileAsyncOperationsUseCase,
        Depends(get_reconcile_async_operations_use_case),
    ],
):
    return use_case.execute(ReconcileAsyncOperationsInput(limit=request.limit))


@router.get("/{operation_id}/poll", response_model=AsyncOperationPollingResponse)
def poll_async_operation(
    operation_id: UUID,
    use_case: Annotated[
        GetAsyncOperationUseCase,
        Depends(get_get_async_operation_use_case),
    ],
):
    operation = use_case.execute(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Async operation not found")

    done = operation.status in TERMINAL_STATUSES
    return AsyncOperationPollingResponse(
        id=operation.id,
        status=operation.status,
        done=done,
        retry_after_seconds=None if done else 2,
        result=operation.result,
        error=operation.error,
        updated_at=operation.updated_at,
    )


@router.get("/{operation_id}", response_model=AsyncOperationResponse)
def get_async_operation(
    operation_id: UUID,
    use_case: Annotated[
        GetAsyncOperationUseCase,
        Depends(get_get_async_operation_use_case),
    ],
):
    operation = use_case.execute(operation_id)
    if operation is None:
        raise HTTPException(status_code=404, detail="Async operation not found")
    return operation


@router.patch("/{operation_id}", response_model=AsyncOperationResponse)
def update_async_operation(
    operation_id: UUID,
    request: UpdateAsyncOperationRequest,
    use_case: Annotated[
        UpdateAsyncOperationUseCase,
        Depends(get_update_async_operation_use_case),
    ],
):
    operation = use_case.execute(
        operation_id,
        UpdateAsyncOperationInput(
            status=request.status,
            result=request.result,
            error=request.error,
        ),
    )
    if operation is None:
        raise HTTPException(status_code=404, detail="Async operation not found")
    return operation

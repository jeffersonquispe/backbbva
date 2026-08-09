from __future__ import annotations

from celery.result import AsyncResult
from celery.states import FAILURE, PENDING, RECEIVED, RETRY, REVOKED, STARTED, SUCCESS

from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionInspector,
    AsyncExecutionSnapshot,
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.infrastructure.entrypoint.worker.celery.celery_app import app


class CeleryAsyncExecutionInspector(AsyncExecutionInspector):
    def inspect(
        self,
        operation: AsyncOperationRecord,
    ) -> AsyncExecutionSnapshot:
        if not operation.external_id:
            return AsyncExecutionSnapshot(
                state=AsyncExecutionState.UNKNOWN,
                detail="Operation has no external execution id",
            )

        result = AsyncResult(operation.external_id, app=app)
        state = result.state

        if state == SUCCESS:
            return AsyncExecutionSnapshot(
                state=AsyncExecutionState.SUCCEEDED,
                result=_serialize_result(result.result),
            )
        if state in {FAILURE, REVOKED}:
            return AsyncExecutionSnapshot(
                state=AsyncExecutionState.FAILED,
                detail=str(result.result or state),
            )
        if state == STARTED:
            return AsyncExecutionSnapshot(state=AsyncExecutionState.RUNNING)
        if state in {PENDING, RECEIVED, RETRY}:
            return AsyncExecutionSnapshot(
                state=AsyncExecutionState.QUEUED,
                detail=state,
            )

        return AsyncExecutionSnapshot(
            state=AsyncExecutionState.UNKNOWN,
            detail=state,
        )


def _serialize_result(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return {"value": str(value)}

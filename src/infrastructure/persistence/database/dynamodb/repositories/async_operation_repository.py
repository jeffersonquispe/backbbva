from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from boto3.dynamodb.conditions import Key

from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "async_operations"
PARTITION = "operation"


class DynamoAsyncOperationRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(
        self, operation: AsyncOperationRecord
    ) -> AsyncOperationRecord:
        self._table.put_item(Item=_to_item(operation))
        return operation

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        response = self._table.get_item(
            Key={
                "partition": PARTITION,
                "operation_id": str(operation_id),
            }
        )
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def list(
        self,
        status: AsyncOperationStatus | None = None,
        limit: int = 100,
    ) -> list[AsyncOperationRecord]:
        if status is None:
            response = self._table.query(
                KeyConditionExpression=Key("partition").eq(PARTITION),
                ScanIndexForward=False,
                Limit=limit,
            )
        else:
            response = self._table.query(
                IndexName="StatusIdx",
                KeyConditionExpression=Key("status").eq(status.value),
                ScanIndexForward=False,
                Limit=limit,
            )
        return [_from_item(item) for item in response.get("Items", [])]

    def update(
        self,
        operation_id: UUID,
        *,
        status: AsyncOperationStatus | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        dispatched_at: datetime | None = None,
        execution_backend: str | None = None,
        external_id: str | None = None,
    ) -> AsyncOperationRecord | None:
        current = self.get(operation_id)
        if current is None:
            return None

        updated = AsyncOperationRecord(
            id=current.id,
            operation_type=current.operation_type,
            status=status or current.status,
            payload=current.payload,
            result=result if result is not None else current.result,
            error=error if error is not None else current.error,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
            created_by=current.created_by,
            dispatched_at=dispatched_at or current.dispatched_at,
            execution_backend=(
                execution_backend
                if execution_backend is not None
                else current.execution_backend
            ),
            external_id=(
                external_id if external_id is not None else current.external_id
            ),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated


def _to_item(operation: AsyncOperationRecord) -> dict[str, Any]:
    return {
        "partition": PARTITION,
        "operation_id": str(operation.id),
        "operation_type": operation.operation_type,
        "status": operation.status.value,
        "payload": operation.payload,
        "result": operation.result,
        "error": operation.error,
        "created_at": operation.created_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
        "created_by": operation.created_by,
        "dispatched_at": (
            operation.dispatched_at.isoformat()
            if operation.dispatched_at
            else None
        ),
        "execution_backend": operation.execution_backend,
        "external_id": operation.external_id,
    }


def _from_item(item: dict[str, Any]) -> AsyncOperationRecord:
    dispatched_at = item.get("dispatched_at")
    return AsyncOperationRecord(
        id=UUID(item["operation_id"]),
        operation_type=item["operation_type"],
        status=AsyncOperationStatus(item["status"]),
        payload=item.get("payload") or {},
        result=item.get("result"),
        error=item.get("error"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        created_by=item.get("created_by"),
        dispatched_at=(
            datetime.fromisoformat(dispatched_at) if dispatched_at else None
        ),
        execution_backend=item.get("execution_backend"),
        external_id=item.get("external_id"),
    )

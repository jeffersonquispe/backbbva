from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.application.ports.alert_port import (
    AlertRecord,
    AlertStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

TABLE_NAME = "alerts"
PARTITION = "alert"


class DynamoAlertRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(self, alert: AlertRecord) -> AlertRecord:
        self._table.put_item(Item=_to_item(alert))
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        response = self._table.get_item(
            Key={"partition": PARTITION, "alert_id": str(alert_id)}
        )
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def update(
        self,
        alert_id: UUID,
        *,
        status: AlertStatus | None = None,
        async_operation_id: UUID | None = None,
        workflow_execution_id: UUID | None = None,
    ) -> AlertRecord | None:
        current = self.get(alert_id)
        if current is None:
            return None

        updated = AlertRecord(
            id=current.id,
            event_id=current.event_id,
            event_type=current.event_type,
            payload=current.payload,
            status=status or current.status,
            customer_id=current.customer_id,
            async_operation_id=async_operation_id
            or current.async_operation_id,
            workflow_execution_id=workflow_execution_id
            or current.workflow_execution_id,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, alert_id: UUID) -> None:
        self._table.delete_item(Key={"partition": PARTITION, "alert_id": str(alert_id)})


def _to_item(alert: AlertRecord) -> dict[str, Any]:
    return {
        "partition": PARTITION,
        "alert_id": str(alert.id),
        "event_id": alert.event_id,
        "event_type": alert.event_type,
        "payload": to_dynamodb(alert.payload),
        "status": alert.status.value,
        "customer_id": alert.customer_id,
        "async_operation_id": (
            str(alert.async_operation_id) if alert.async_operation_id else None
        ),
        "workflow_execution_id": (
            str(alert.workflow_execution_id)
            if alert.workflow_execution_id
            else None
        ),
        "created_at": alert.created_at.isoformat(),
        "updated_at": alert.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> AlertRecord:
    return AlertRecord(
        id=UUID(item["alert_id"]),
        event_id=item["event_id"],
        event_type=item["event_type"],
        payload=from_dynamodb(item.get("payload") or {}),
        status=AlertStatus(item["status"]),
        customer_id=item.get("customer_id"),
        async_operation_id=(
            UUID(item["async_operation_id"])
            if item.get("async_operation_id")
            else None
        ),
        workflow_execution_id=(
            UUID(item["workflow_execution_id"])
            if item.get("workflow_execution_id")
            else None
        ),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaRepository,
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

TABLE_NAME = "alert_schema_versions"


class DynamoAlertSchemaRepository(AlertSchemaRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def get_active(self) -> AlertSchemaVersion | None:
        result = self._table.scan(
            FilterExpression="#status = :active",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":active": "active"},
        )
        items = result.get("Items", [])
        return _from_item(items[0]) if items else None

    def list_versions(self) -> list[AlertSchemaVersion]:
        result = self._table.scan()
        return sorted(
            (_from_item(item) for item in result.get("Items", [])),
            key=lambda item: item.version,
            reverse=True,
        )

    def get(self, version: int) -> AlertSchemaVersion | None:
        item = self._table.get_item(Key={"version": version}).get("Item")
        return _from_item(item) if item else None

    def save_draft(self, schema: AlertSchemaVersion) -> AlertSchemaVersion:
        self._table.put_item(Item=to_dynamodb(_to_item(schema)))
        return schema

    def update(self, schema: AlertSchemaVersion) -> AlertSchemaVersion:
        return self.save_draft(schema)


def _to_item(schema: AlertSchemaVersion) -> dict[str, Any]:
    payload = asdict(schema)
    payload["status"] = schema.status.value
    payload["fields"] = [
        {**asdict(item), "data_source": item.data_source.value, "type": item.type.value}
        for item in schema.fields
    ]
    payload["proposed_at"] = (
        schema.proposed_at.isoformat() if schema.proposed_at else None
    )
    payload["approved_at"] = (
        schema.approved_at.isoformat() if schema.approved_at else None
    )
    payload["comparison"] = schema.comparison
    payload["impact"] = schema.impact
    return payload


def _from_item(item: dict[str, Any]) -> AlertSchemaVersion:
    value = from_dynamodb(item)
    return AlertSchemaVersion(
        version=int(value["version"]),
        status=AlertSchemaStatus(value["status"]),
        fields=[
            AlertSchemaField(
                **{
                    **field,
                    "data_source": AlertSchemaDataSource(field["data_source"]),
                    "type": AlertSchemaFieldType(field["type"]),
                }
            )
            for field in value.get("fields", [])
        ],
        field_roles=value.get("field_roles") or {},
        proposed_by=value.get("proposed_by"),
        proposed_at=datetime.fromisoformat(value["proposed_at"])
        if value.get("proposed_at")
        else None,
        approved_by=value.get("approved_by"),
        approved_at=datetime.fromisoformat(value["approved_at"])
        if value.get("approved_at")
        else None,
        impact_acknowledged=bool(value.get("impact_acknowledged", False)),
        based_on_version=value.get("based_on_version"),
        comparison=value.get("comparison") or {},
        impact=value.get("impact") or [],
    )

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from boto3.dynamodb.conditions import Key

from src.application.ports.alert_field_mapping_port import (
    AlertFieldMapping,
    AlertFieldMappingRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

ALERT_FIELD_MAPPINGS_TABLE_NAME = "alert_field_mappings"


class DynamoAlertFieldMappingRepository(AlertFieldMappingRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(ALERT_FIELD_MAPPINGS_TABLE_NAME)

    def get(self, dataset_name: str) -> AlertFieldMapping | None:
        response = self._table.query(
            KeyConditionExpression=Key("dataset_name").eq(dataset_name),
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items") or []
        item = items[0] if items else None
        if item is None:
            return None
        return _from_item(item)

    def save(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        self._table.put_item(Item=_to_item(mapping))
        return mapping

    def delete(self, dataset_name: str) -> None:
        response = self._table.query(
            KeyConditionExpression=Key("dataset_name").eq(dataset_name),
            ProjectionExpression="dataset_name, saved_at",
        )
        with self._table.batch_writer() as batch:
            for item in response.get("Items") or []:
                batch.delete_item(Key=item)


def _to_item(mapping: AlertFieldMapping) -> dict[str, Any]:
    return {
        "dataset_name": mapping.dataset_name,
        # The suffix prevents two saves in the same clock tick from
        # overwriting one another while preserving chronological ordering.
        "saved_at": f"{mapping.updated_at.isoformat()}#{uuid4().hex}",
        "schema_version": mapping.schema_version,
        "mappings": mapping.mappings,
        "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
    }


def _from_item(item: dict[str, Any]) -> AlertFieldMapping:
    updated_at = item.get("updated_at")
    return AlertFieldMapping(
        dataset_name=item["dataset_name"],
        schema_version=int(item["schema_version"]),
        mappings=dict(item.get("mappings") or {}),
        updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
    )

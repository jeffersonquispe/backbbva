from __future__ import annotations

from datetime import datetime
from typing import Any

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
        response = self._table.get_item(Key={"dataset_name": dataset_name})
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def upsert(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        self._table.put_item(Item=_to_item(mapping))
        return mapping

    def delete(self, dataset_name: str) -> None:
        self._table.delete_item(Key={"dataset_name": dataset_name})


def _to_item(mapping: AlertFieldMapping) -> dict[str, Any]:
    return {
        "dataset_name": mapping.dataset_name,
        "mappings": mapping.mappings,
        "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
    }


def _from_item(item: dict[str, Any]) -> AlertFieldMapping:
    updated_at = item.get("updated_at")
    return AlertFieldMapping(
        dataset_name=item["dataset_name"],
        mappings=dict(item.get("mappings") or {}),
        updated_at=datetime.fromisoformat(updated_at) if updated_at else None,
    )

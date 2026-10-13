from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.tag_catalog_port import (
    TagCatalogRepository,
    TagCategory,
    TagEntry,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TAG_CATALOG_TABLE_NAME = "tag_catalog"


class DynamoTagCatalogRepository(TagCatalogRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TAG_CATALOG_TABLE_NAME)

    def create(self, entry: TagEntry) -> TagEntry:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, category: TagCategory, tag_id: str) -> TagEntry | None:
        response = self._table.get_item(
            Key={"category": category.value, "tag_id": tag_id}
        )
        item = response.get("Item")
        return _from_item(item) if item else None

    def list_by_category(
        self, category: TagCategory, *, active_only: bool = False
    ) -> list[TagEntry]:
        response = self._table.query(
            KeyConditionExpression=Key("category").eq(category.value),
        )
        entries = [_from_item(item) for item in response.get("Items", [])]
        if active_only:
            entries = [entry for entry in entries if entry.active]
        return entries

    def update(
        self,
        category: TagCategory,
        tag_id: str,
        *,
        value: str | None = None,
        active: bool | None = None,
    ) -> TagEntry | None:
        current = self.get(category, tag_id)
        if current is None:
            return None
        updated = TagEntry(
            id=current.id,
            category=current.category,
            value=value if value is not None else current.value,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, category: TagCategory, tag_id: str) -> None:
        self._table.delete_item(Key={"category": category.value, "tag_id": tag_id})


def _to_item(entry: TagEntry) -> dict[str, Any]:
    return {
        "category": entry.category.value,
        "tag_id": entry.id,
        "value": entry.value,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> TagEntry:
    return TagEntry(
        id=item["tag_id"],
        category=TagCategory(item["category"]),
        value=item["value"],
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

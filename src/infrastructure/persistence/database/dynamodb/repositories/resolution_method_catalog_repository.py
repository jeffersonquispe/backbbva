from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.application.ports.configuration_port import ResolutionTag
from src.application.ports.resolution_method_catalog_port import (
    ResolutionMethod,
    ResolutionMethodCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

RESOLUTION_METHOD_CATALOG_TABLE_NAME = "resolution_method_catalog"


class DynamoResolutionMethodCatalogRepository(ResolutionMethodCatalogRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(RESOLUTION_METHOD_CATALOG_TABLE_NAME)

    def create(self, entry: ResolutionMethod) -> ResolutionMethod:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, entry_id: str) -> ResolutionMethod | None:
        response = self._table.get_item(Key={"id": entry_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(self, *, active_only: bool = False) -> list[ResolutionMethod]:
        response = self._table.scan()
        entries = [_from_item(item) for item in response.get("Items", [])]
        if active_only:
            entries = [entry for entry in entries if entry.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        resolution_tag: ResolutionTag | None = None,
        active: bool | None = None,
    ) -> ResolutionMethod | None:
        current = self.get(entry_id)
        if current is None:
            return None
        updated = ResolutionMethod(
            id=current.id,
            value=value if value is not None else current.value,
            resolution_tag=resolution_tag if resolution_tag is not None else current.resolution_tag,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, entry_id: str) -> None:
        self._table.delete_item(Key={"id": entry_id})


def _to_item(entry: ResolutionMethod) -> dict[str, Any]:
    return {
        "id": entry.id,
        "value": entry.value,
        "resolution_tag": entry.resolution_tag.value,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> ResolutionMethod:
    return ResolutionMethod(
        id=item["id"],
        value=item["value"],
        resolution_tag=ResolutionTag(item["resolution_tag"]),
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

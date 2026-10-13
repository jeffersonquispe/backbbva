from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.application.ports.marcacion_catalog_port import (
    MarcacionCatalogRepository,
    MarcacionCategory,
    RiskLabel,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

MARCACION_CATALOG_TABLE_NAME = "marcacion_catalog"


class DynamoMarcacionCatalogRepository(MarcacionCatalogRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(MARCACION_CATALOG_TABLE_NAME)

    def create(self, entry: MarcacionCategory) -> MarcacionCategory:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, entry_id: str) -> MarcacionCategory | None:
        response = self._table.get_item(Key={"id": entry_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(self, *, active_only: bool = False) -> list[MarcacionCategory]:
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
        risk_label: RiskLabel | None = None,
        active: bool | None = None,
    ) -> MarcacionCategory | None:
        current = self.get(entry_id)
        if current is None:
            return None
        updated = MarcacionCategory(
            id=current.id,
            value=value if value is not None else current.value,
            risk_label=risk_label if risk_label is not None else current.risk_label,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, entry_id: str) -> None:
        self._table.delete_item(Key={"id": entry_id})


def _to_item(entry: MarcacionCategory) -> dict[str, Any]:
    return {
        "id": entry.id,
        "value": entry.value,
        "risk_label": entry.risk_label.value,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> MarcacionCategory:
    return MarcacionCategory(
        id=item["id"],
        value=item["value"],
        risk_label=RiskLabel(item["risk_label"]),
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryEntry,
    TaxonomyLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TAXONOMY_LIBRARY_TABLE_NAME = "library_taxonomies"


class DynamoTaxonomyLibraryRepository(TaxonomyLibraryRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TAXONOMY_LIBRARY_TABLE_NAME)

    def create(self, entry: TaxonomyLibraryEntry) -> TaxonomyLibraryEntry:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, entry_id: str) -> TaxonomyLibraryEntry | None:
        response = self._table.get_item(Key={"id": entry_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(self, *, active_only: bool = False) -> list[TaxonomyLibraryEntry]:
        response = self._table.scan()
        entries = [_from_item(item) for item in response.get("Items", [])]
        if active_only:
            entries = [entry for entry in entries if entry.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
        examples: list[str] | None = None,
        active: bool | None = None,
    ) -> TaxonomyLibraryEntry | None:
        current = self.get(entry_id)
        if current is None:
            return None
        updated = TaxonomyLibraryEntry(
            id=current.id,
            code=code if code is not None else current.code,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            variables=variables if variables is not None else current.variables,
            examples=examples if examples is not None else current.examples,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, entry_id: str) -> None:
        self._table.delete_item(Key={"id": entry_id})


def _to_item(entry: TaxonomyLibraryEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "code": entry.code,
        "name": entry.name,
        "description": entry.description,
        "variables": entry.variables,
        "examples": entry.examples,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> TaxonomyLibraryEntry:
    return TaxonomyLibraryEntry(
        id=item["id"],
        code=item["code"],
        name=item["name"],
        description=item.get("description", ""),
        variables=list(item.get("variables", [])),
        examples=list(item.get("examples", [])),
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.application.ports.flag_library_port import (
    FlagLibraryEntry,
    FlagLibraryRepository,
)
from src.domain.configurations.entities import (
    FlagType,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

FLAG_LIBRARY_TABLE_NAME = "library_flags"


class DynamoFlagLibraryRepository(FlagLibraryRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(FLAG_LIBRARY_TABLE_NAME)

    def create(self, entry: FlagLibraryEntry) -> FlagLibraryEntry:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, entry_id: str) -> FlagLibraryEntry | None:
        response = self._table.get_item(Key={"id": entry_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(self, *, active_only: bool = False) -> list[FlagLibraryEntry]:
        response = self._table.scan()
        entries = [_from_item(item) for item in response.get("Items", [])]
        if active_only:
            entries = [entry for entry in entries if entry.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        flag_type: FlagType | None = None,
        name: str | None = None,
        description: str | None = None,
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
    ) -> FlagLibraryEntry | None:
        current = self.get(entry_id)
        if current is None:
            return None
        updated = FlagLibraryEntry(
            id=current.id,
            flag_type=flag_type if flag_type is not None else current.flag_type,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            evolved_variables=(
                evolved_variables
                if evolved_variables is not None
                else current.evolved_variables
            ),
            modus_operandi_library_ids=(
                modus_operandi_library_ids
                if modus_operandi_library_ids is not None
                else current.modus_operandi_library_ids
            ),
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
            embedding=embedding if embedding is not None else current.embedding,
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, entry_id: str) -> None:
        self._table.delete_item(Key={"id": entry_id})


def _to_item(entry: FlagLibraryEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "flag_type": entry.flag_type.value,
        "name": entry.name,
        "description": entry.description,
        "evolved_variables": entry.evolved_variables,
        "modus_operandi_library_ids": entry.modus_operandi_library_ids,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "embedding": entry.embedding,
    }


def _from_item(item: dict[str, Any]) -> FlagLibraryEntry:
    return FlagLibraryEntry(
        id=item["id"],
        flag_type=FlagType(item["flag_type"]),
        name=item["name"],
        description=item.get("description", ""),
        evolved_variables=list(item.get("evolved_variables", [])),
        modus_operandi_library_ids=list(item.get("modus_operandi_library_ids", [])),
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        embedding=[float(v) for v in item["embedding"]]
        if item.get("embedding") is not None
        else None,
    )

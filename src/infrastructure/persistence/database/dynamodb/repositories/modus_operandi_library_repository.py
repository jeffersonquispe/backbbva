from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryEntry,
    ModusOperandiLibraryRepository,
    ModusOperandiPlaybook,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_item_mapping import (
    _shortage_behavior_from_item,
)

MODUS_OPERANDI_LIBRARY_TABLE_NAME = "library_modus_operandi"


class DynamoModusOperandiLibraryRepository(ModusOperandiLibraryRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(MODUS_OPERANDI_LIBRARY_TABLE_NAME)

    def create(self, entry: ModusOperandiLibraryEntry) -> ModusOperandiLibraryEntry:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, entry_id: str) -> ModusOperandiLibraryEntry | None:
        response = self._table.get_item(Key={"id": entry_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(self, *, active_only: bool = False) -> list[ModusOperandiLibraryEntry]:
        response = self._table.scan()
        entries = [_from_item(item) for item in response.get("Items", [])]
        if active_only:
            entries = [entry for entry in entries if entry.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
        playbook: ModusOperandiPlaybook | None = None,
    ) -> ModusOperandiLibraryEntry | None:
        current = self.get(entry_id)
        if current is None:
            return None
        updated = ModusOperandiLibraryEntry(
            id=current.id,
            title=title if title is not None else current.title,
            narrative=narrative if narrative is not None else current.narrative,
            taxonomy_library_id=(
                taxonomy_library_id if taxonomy_library_id is not None else current.taxonomy_library_id
            ),
            evolved_variables=(
                evolved_variables if evolved_variables is not None else current.evolved_variables
            ),
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
            embedding=embedding if embedding is not None else current.embedding,
            playbook=playbook if playbook is not None else current.playbook,
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, entry_id: str) -> None:
        self._table.delete_item(Key={"id": entry_id})


def _to_item(entry: ModusOperandiLibraryEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "title": entry.title,
        "narrative": entry.narrative,
        "taxonomy_library_id": entry.taxonomy_library_id,
        "evolved_variables": entry.evolved_variables,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "embedding": entry.embedding,
        "playbook": asdict(entry.playbook) if entry.playbook is not None else None,
    }


def _from_item(item: dict[str, Any]) -> ModusOperandiLibraryEntry:
    return ModusOperandiLibraryEntry(
        id=item["id"],
        title=item["title"],
        narrative=item["narrative"],
        taxonomy_library_id=item["taxonomy_library_id"],
        evolved_variables=list(item.get("evolved_variables", [])),
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        embedding=[float(v) for v in item["embedding"]] if item.get("embedding") is not None else None,
        playbook=_playbook_from_item(item.get("playbook")),
    )


def _playbook_from_item(item: dict[str, Any] | None) -> ModusOperandiPlaybook | None:
    if not item:
        return None
    return ModusOperandiPlaybook(
        strategy=item.get("strategy") or "",
        resolution=_shortage_behavior_from_item(
            item.get("resolution") or {"resolution_tag": "scale_to_analyst"}
        ),
        if_no_voicebot=_shortage_behavior_from_item(item.get("if_no_voicebot") or {}),
        if_no_analyst=_shortage_behavior_from_item(item.get("if_no_analyst") or {}),
    )

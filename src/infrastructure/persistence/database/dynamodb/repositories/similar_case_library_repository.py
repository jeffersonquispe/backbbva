from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryEntry,
    SimilarCaseLibraryRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

SIMILAR_CASE_LIBRARY_TABLE_NAME = "library_similar_cases"


class DynamoSimilarCaseLibraryRepository(SimilarCaseLibraryRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(SIMILAR_CASE_LIBRARY_TABLE_NAME)

    def create(self, entry: SimilarCaseLibraryEntry) -> SimilarCaseLibraryEntry:
        self._table.put_item(Item=_to_item(entry))
        return entry

    def get(self, entry_id: str) -> SimilarCaseLibraryEntry | None:
        response = self._table.get_item(Key={"id": entry_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(self, *, active_only: bool = False) -> list[SimilarCaseLibraryEntry]:
        response = self._table.scan()
        entries = [_from_item(item) for item in response.get("Items", [])]
        if active_only:
            entries = [entry for entry in entries if entry.active]
        return entries

    def update(
        self,
        entry_id: str,
        *,
        text: str | None = None,
        modus_operandi_library_id: str | None = None,
        taxonomy_library_id: str | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
    ) -> SimilarCaseLibraryEntry | None:
        current = self.get(entry_id)
        if current is None:
            return None
        updated = SimilarCaseLibraryEntry(
            id=current.id,
            text=text if text is not None else current.text,
            modus_operandi_library_id=(
                modus_operandi_library_id
                if modus_operandi_library_id is not None
                else current.modus_operandi_library_id
            ),
            taxonomy_library_id=(
                taxonomy_library_id if taxonomy_library_id is not None else current.taxonomy_library_id
            ),
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
            embedding=embedding if embedding is not None else current.embedding,
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, entry_id: str) -> None:
        self._table.delete_item(Key={"id": entry_id})


def _to_item(entry: SimilarCaseLibraryEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "text": entry.text,
        "modus_operandi_library_id": entry.modus_operandi_library_id,
        "taxonomy_library_id": entry.taxonomy_library_id,
        "active": entry.active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "embedding": entry.embedding,
    }


def _from_item(item: dict[str, Any]) -> SimilarCaseLibraryEntry:
    return SimilarCaseLibraryEntry(
        id=item["id"],
        text=item["text"],
        modus_operandi_library_id=item["modus_operandi_library_id"],
        taxonomy_library_id=item["taxonomy_library_id"],
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        embedding=[float(v) for v in item["embedding"]] if item.get("embedding") is not None else None,
    )

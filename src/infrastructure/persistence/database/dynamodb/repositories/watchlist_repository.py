from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.application.ports.watchlist_port import (
    Watchlist,
    WatchlistRepository,
    WatchlistType,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

WATCHLIST_TABLE_NAME = "watchlists"


class DynamoWatchlistRepository(WatchlistRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(WATCHLIST_TABLE_NAME)

    def create(self, watchlist: Watchlist) -> Watchlist:
        self._table.put_item(Item=_to_item(watchlist))
        return watchlist

    def get(self, watchlist_id: str) -> Watchlist | None:
        response = self._table.get_item(Key={"id": watchlist_id})
        item = response.get("Item")
        return _from_item(item) if item else None

    def list(
        self,
        *,
        list_type: WatchlistType | None = None,
        active_only: bool = False,
    ) -> list[Watchlist]:
        response = self._table.scan()
        watchlists = [_from_item(item) for item in response.get("Items", [])]
        if list_type is not None:
            watchlists = [w for w in watchlists if w.list_type == list_type]
        if active_only:
            watchlists = [w for w in watchlists if w.active]
        return watchlists

    def update(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        elements: list[str] | None = None,
        active: bool | None = None,
    ) -> Watchlist | None:
        current = self.get(watchlist_id)
        if current is None:
            return None
        updated = Watchlist(
            id=current.id,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            list_type=current.list_type,
            elements=elements if elements is not None else current.elements,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def delete(self, watchlist_id: str) -> None:
        self._table.delete_item(Key={"id": watchlist_id})


def _to_item(watchlist: Watchlist) -> dict[str, Any]:
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "description": watchlist.description,
        "list_type": watchlist.list_type.value,
        "elements": list(watchlist.elements),
        "active": watchlist.active,
        "created_at": watchlist.created_at.isoformat(),
        "updated_at": watchlist.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> Watchlist:
    return Watchlist(
        id=item["id"],
        name=item["name"],
        description=item["description"],
        list_type=WatchlistType(item["list_type"]),
        elements=list(item.get("elements", [])),
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

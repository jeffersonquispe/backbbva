from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.watchlist_port import (
    Watchlist,
    WatchlistRepository,
    WatchlistType,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

WATCHLIST_TABLE_NAME = "watchlists"
WATCHLIST_ELEMENTS_TABLE_NAME = "watchlist_elements"

# BatchWriteItem/BatchGetItem both cap at 25/100 items per call.
_BATCH_WRITE_SIZE = 25
_BATCH_GET_SIZE = 100


class DynamoWatchlistRepository(WatchlistRepository):
    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        self._resource = resource
        self._table = resource.Table(WATCHLIST_TABLE_NAME)
        self._elements_table = resource.Table(WATCHLIST_ELEMENTS_TABLE_NAME)

    def create(self, watchlist: Watchlist) -> Watchlist:
        self._table.put_item(Item=_to_item(watchlist))
        return watchlist

    def get(self, watchlist_id: str) -> Watchlist | None:
        response = self._table.get_item(Key={"id": watchlist_id})
        item = response.get("Item")
        if item is None:
            return None
        watchlist = _from_item(item)
        watchlist.element_count = self.count_elements(watchlist_id)
        return watchlist

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
        for watchlist in watchlists:
            watchlist.element_count = self.count_elements(watchlist.id)
        return watchlists

    def update(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> Watchlist | None:
        response = self._table.get_item(Key={"id": watchlist_id})
        item = response.get("Item")
        if item is None:
            return None
        current = _from_item(item)
        updated = Watchlist(
            id=current.id,
            name=name if name is not None else current.name,
            description=description if description is not None else current.description,
            list_type=current.list_type,
            active=active if active is not None else current.active,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        self._table.put_item(Item=_to_item(updated))
        updated.element_count = self.count_elements(watchlist_id)
        return updated

    def delete(self, watchlist_id: str) -> None:
        self._table.delete_item(Key={"id": watchlist_id})
        self._delete_all_elements(watchlist_id)

    # --- Elements ------------------------------------------------------

    def add_elements(self, watchlist_id: str, values: list[str]) -> int:
        normalized = _normalize_dedup(values)
        if not normalized:
            return 0
        with self._elements_table.batch_writer(
            overwrite_by_pkeys=["watchlist_id", "value"]
        ) as batch:
            for value, raw_value in normalized.items():
                batch.put_item(
                    Item={
                        "watchlist_id": watchlist_id,
                        "value": value,
                        "raw_value": raw_value,
                    }
                )
        return len(normalized)

    def remove_elements(self, watchlist_id: str, values: list[str]) -> int:
        normalized = _normalize_dedup(values)
        if not normalized:
            return 0
        with self._elements_table.batch_writer() as batch:
            for value in normalized:
                batch.delete_item(Key={"watchlist_id": watchlist_id, "value": value})
        return len(normalized)

    def count_elements(self, watchlist_id: str) -> int:
        # ponytail: full paginated COUNT scan of the watchlist's elements.
        # Cheap enough at "tens of thousands" (admin-only traffic, not the
        # hot path check_membership uses). If watchlist admin pages get
        # slow at much larger scale, switch to an atomic counter
        # (UpdateItem ADD) maintained by add/remove_elements instead.
        count = 0
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("watchlist_id").eq(watchlist_id),
            "Select": "COUNT",
        }
        while True:
            response = self._elements_table.query(**kwargs)
            count += response.get("Count", 0)
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return count

    def list_elements(
        self,
        watchlist_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[str], str | None]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("watchlist_id").eq(watchlist_id),
            "Limit": limit,
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)
        response = self._elements_table.query(**kwargs)
        values = [item["raw_value"] for item in response.get("Items", [])]
        last_key = response.get("LastEvaluatedKey")
        next_cursor = _encode_cursor(last_key) if last_key else None
        return values, next_cursor

    def elements_containing(self, watchlist_ids: list[str], value: str) -> set[str]:
        normalized = value.strip().casefold()
        if not normalized or not watchlist_ids:
            return set()
        found: set[str] = set()
        for chunk in _chunks(watchlist_ids, _BATCH_GET_SIZE):
            keys = [{"watchlist_id": wid, "value": normalized} for wid in chunk]
            request = {WATCHLIST_ELEMENTS_TABLE_NAME: {"Keys": keys}}
            while request:
                response = self._resource.batch_get_item(RequestItems=request)
                for item in response.get("Responses", {}).get(
                    WATCHLIST_ELEMENTS_TABLE_NAME, []
                ):
                    found.add(item["watchlist_id"])
                request = response.get("UnprocessedKeys") or None
        return found

    def _delete_all_elements(self, watchlist_id: str) -> None:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("watchlist_id").eq(watchlist_id),
            "ProjectionExpression": "#v",
            "ExpressionAttributeNames": {"#v": "value"},
        }
        with self._elements_table.batch_writer() as batch:
            while True:
                response = self._elements_table.query(**kwargs)
                for item in response.get("Items", []):
                    batch.delete_item(
                        Key={"watchlist_id": watchlist_id, "value": item["value"]}
                    )
                last_key = response.get("LastEvaluatedKey")
                if not last_key:
                    break
                kwargs["ExclusiveStartKey"] = last_key


def _normalize_dedup(values: list[str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for value in values:
        raw = value.strip()
        key = raw.casefold()
        if key:
            normalized[key] = raw
    return normalized


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _encode_cursor(key: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(key).encode()).decode()


def _decode_cursor(cursor: str) -> dict[str, Any]:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())


def _to_item(watchlist: Watchlist) -> dict[str, Any]:
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "description": watchlist.description,
        "list_type": watchlist.list_type.value,
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
        active=bool(item.get("active", True)),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

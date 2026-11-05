"""alert_id -> archived day object + byte range (ArchiveIndexPort)."""

from __future__ import annotations

from datetime import date
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.fraud_history_archive_index_port import (
    ArchiveIndexPort,
)
from src.application.ports.fraud_history_archive_port import (
    ArchiveIndexEntry,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "fraud_history_archive_index"


class DynamoFraudHistoryArchiveIndex(ArchiveIndexPort):
    def __init__(self, table: Any | None = None) -> None:
        self._table = (
            table if table is not None else get_dynamodb_resource().Table(TABLE_NAME)
        )

    def put_many(self, entries: list[ArchiveIndexEntry]) -> None:
        # Plain puts: re-archiving an alert (partial delete re-run) points the
        # index at the newest object that holds it.
        with self._table.batch_writer() as batch:
            for entry in entries:
                item: dict[str, Any] = {
                    "alert_id": entry.alert_id,
                    "created_day": entry.created_day.isoformat(),
                    "object_key": entry.object_key,
                }
                if entry.offset is not None and entry.length is not None:
                    item["offset"] = entry.offset
                    item["length"] = entry.length
                if entry.record_sha256:
                    item["record_sha256"] = entry.record_sha256
                if entry.event_id:
                    item["event_id"] = entry.event_id
                batch.put_item(Item=item)

    def get(self, alert_id: str) -> ArchiveIndexEntry | None:
        item = self._table.get_item(
            Key={"alert_id": alert_id}, ConsistentRead=True
        ).get("Item")
        return _entry(item) if item else None

    def find_by_event_id(self, event_id: str) -> list[ArchiveIndexEntry]:
        return [
            _entry(item)
            for item in self._query(
                IndexName="EventIdIdx",
                KeyConditionExpression=Key("event_id").eq(event_id),
            )
        ]

    def list_day(self, created_day: date, limit: int) -> list[ArchiveIndexEntry]:
        return [
            _entry(item)
            for item in self._query(
                IndexName="CreatedDayIdx",
                KeyConditionExpression=Key("created_day").eq(created_day.isoformat()),
                limit=limit,
            )
        ]

    def _query(self, limit: int = 100, **kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while len(items) < limit:
            page = self._table.query(**kwargs)
            items.extend(page.get("Items", []))
            last = page.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        return items[:limit]


def _entry(item: dict[str, Any]) -> ArchiveIndexEntry:
    return ArchiveIndexEntry(
        alert_id=item["alert_id"],
        created_day=date.fromisoformat(item["created_day"]),
        object_key=item["object_key"],
        offset=int(item["offset"]) if "offset" in item else None,
        length=int(item["length"]) if "length" in item else None,
        record_sha256=item.get("record_sha256"),
        event_id=item.get("event_id"),
    )

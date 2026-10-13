from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

CAPACITY_TABLE_NAME = "operations_capacity"
CAPACITY_RECORD_ID = "current"

# Used only if the singleton row hasn't been seeded yet (see
# dynamodb/manager.py's seed_defaults) - keeps the analyst step from
# hard-failing on a fresh/unseeded environment.
_FALLBACK_CAPACITY = OperationsCapacityRecord(
    analysts=ChannelCapacity(available=0, status="unavailable"),
    voicebot=ChannelCapacity(available=0, status="unavailable"),
    bidi=ChannelCapacity(available=0, status="unavailable"),
    updated_at=datetime.fromtimestamp(0, tz=UTC),
)


class DynamoOperationsCapacityRepository(OperationsCapacityPort):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(CAPACITY_TABLE_NAME)

    def get_capacity(self) -> OperationsCapacityRecord:
        response = self._table.get_item(Key={"record_id": CAPACITY_RECORD_ID})
        item = response.get("Item")
        if item is None:
            return _FALLBACK_CAPACITY
        return _from_item(item)

    def put_capacity(self, record: OperationsCapacityRecord) -> OperationsCapacityRecord:
        self._table.put_item(Item=_to_item(record))
        return record


def _channel_to_item(channel: ChannelCapacity) -> dict[str, Any]:
    return {"available": channel.available, "status": channel.status}


def _channel_from_item(item: dict[str, Any]) -> ChannelCapacity:
    return ChannelCapacity(
        available=int(item.get("available") or 0),
        status=str(item.get("status") or "unavailable"),
    )


def _to_item(record: OperationsCapacityRecord) -> dict[str, Any]:
    return {
        "record_id": CAPACITY_RECORD_ID,
        "analysts": _channel_to_item(record.analysts),
        "voicebot": _channel_to_item(record.voicebot),
        "bidi": _channel_to_item(record.bidi),
        "updated_at": record.updated_at.isoformat(),
    }


def _from_item(item: dict[str, Any]) -> OperationsCapacityRecord:
    return OperationsCapacityRecord(
        analysts=_channel_from_item(item.get("analysts") or {}),
        voicebot=_channel_from_item(item.get("voicebot") or {}),
        bidi=_channel_from_item(item.get("bidi") or {}),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

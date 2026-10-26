from __future__ import annotations

import gzip
import hashlib
import heapq
import itertools
import json
from collections import deque
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.application.ports.audit_log_archive_port import AuditLogArchivePort
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.monitoring.audit_collector import (
    record_audit,
    suppress_audit_collection,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "audit_log"
ARCHIVE_PREFIX = "audit-log-archive"
_LOCK_PARTITION = "_aria_audit_archive"
_LOCK_ID = "flush-lock"
_LOCK_SECONDS = 300
_CHUNK_SIZE = 500
_HOT_ITEM_HEADROOM = 100
_COMPACT_OBJECT_MIN_BYTES = 8 * 1024


class DynamoAuditLogArchiveRepository(AuditLogArchivePort):
    """Moves old audit rows to immutable, date-partitioned gzip JSONL objects."""

    def __init__(
        self,
        storage: ObjectStoragePort,
        *,
        table: Any | None = None,
    ) -> None:
        self._table = (
            table if table is not None else get_dynamodb_resource().Table(TABLE_NAME)
        )
        self._storage = storage

    def flush(self, *, max_hot_items: int, retention_days: int) -> dict[str, int]:
        owner = self._acquire_lock()
        if owner is None:
            return {
                "busy": 1,
                "hot_items_before": 0,
                "archived_items": 0,
                "deleted_items": 0,
                "archive_objects": 0,
                "hot_items_after_estimate": 0,
            }
        try:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            expired_items, expired_objects = self._archive_expired(cutoff, owner)
            retained_limit = max_hot_items
            if max_hot_items > _HOT_ITEM_HEADROOM:
                retained_limit -= _HOT_ITEM_HEADROOM
            recent_items, excess_items, excess_objects = self._archive_recent_overflow(
                cutoff, retained_limit, owner
            )
            archived = expired_items + excess_items
            objects = expired_objects + excess_objects
            return {
                "busy": 0,
                "hot_items_before": expired_items + recent_items,
                "archived_items": archived,
                "deleted_items": archived,
                "archive_objects": objects,
                "hot_items_after_estimate": recent_items - excess_items,
            }
        finally:
            self._release_lock(owner)

    def query(
        self, *, from_date: str, to_date: str, limit: int
    ) -> list[dict[str, Any]]:
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        latest: dict[str, dict[str, Any]] = {}
        heap: list[tuple[str, int]] = []
        sequence = itertools.count()

        def consider(row: dict[str, Any]) -> None:
            log_id = str(row.get("log_id", ""))
            if not log_id or log_id in latest:
                return
            if len(latest) == limit and log_id <= heap[0][0]:
                return
            if len(latest) == limit:
                oldest_id, _ = heapq.heappop(heap)
                latest.pop(oldest_id, None)
            latest[log_id] = row
            heapq.heappush(heap, (log_id, next(sequence)))

        current = end
        while current >= start:
            day = current.isoformat()
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("partition").eq(day),
                "ScanIndexForward": False,
                "Limit": limit,
            }
            while True:
                response = self._table.query(**kwargs)
                for row in response.get("Items", []):
                    consider(row)
                last = response.get("LastEvaluatedKey")
                if not last or len(latest) == limit:
                    break
                kwargs["ExclusiveStartKey"] = last
            prefix = f"{ARCHIVE_PREFIX}/date={day}/"
            for obj in self._storage.list_objects(prefix=prefix):
                compressed = self._storage.get_bytes(obj.key)
                for line in gzip.decompress(compressed).splitlines():
                    if line:
                        row = json.loads(line)
                        consider(row)
            if len(latest) == limit and current.isoformat() < heap[0][0][:10]:
                break
            current -= timedelta(days=1)
        return sorted(latest.values(), key=lambda row: str(row["log_id"]), reverse=True)

    def _archive_expired(self, cutoff: datetime, owner: str) -> tuple[int, int]:
        cutoff_day = cutoff.date().isoformat()
        target_day = (cutoff.date() - timedelta(days=1)).isoformat()
        state = self._table.get_item(
            Key={"partition": _LOCK_PARTITION, "log_id": _LOCK_ID},
            ConsistentRead=True,
        ).get("Item", {})
        archived = objects = 0
        cursor = state.get("archive_through_day")
        if cursor:
            current = date.fromisoformat(str(cursor)) + timedelta(days=1)
            target = date.fromisoformat(target_day)
            while current <= target:
                item_count, object_count = self._archive_day(
                    current.isoformat(), cutoff, owner
                )
                archived += item_count
                objects += object_count
                self._save_archive_cursor(current.isoformat(), owner)
                current += timedelta(days=1)
        else:
            kwargs: dict[str, Any] = {
                "FilterExpression": Attr("partition").lt(cutoff_day)
                & Attr("partition").ne(_LOCK_PARTITION),
            }
            while True:
                self._refresh_lock(owner)
                page = self._table.scan(**kwargs)
                rows = [
                    row
                    for row in page.get("Items", [])
                    if row.get("partition") != _LOCK_PARTITION
                    and _key_time(row) < cutoff
                ]
                item_count, object_count = self._archive_rows(rows)
                archived += item_count
                objects += object_count
                last = page.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
            self._save_archive_cursor(target_day, owner)
        # Partition keys are days; inspect the cutoff day to preserve the
        # exact five-day window rather than expiring the whole calendar day.
        cutoff_rows = [
            row
            for row in self._query_day(cutoff_day, owner=owner)
            if _key_time(row) < cutoff
        ]
        for offset in range(0, len(cutoff_rows), _CHUNK_SIZE):
            item_count, object_count = self._archive_rows(
                cutoff_rows[offset : offset + _CHUNK_SIZE]
            )
            archived += item_count
            objects += object_count
        objects += self._compact_archive_day(cutoff_day, owner)
        return archived, objects

    def _archive_day(self, day: str, cutoff: datetime, owner: str) -> tuple[int, int]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("partition").eq(day),
            "ScanIndexForward": True,
        }
        archived = objects = 0
        chunk: list[dict[str, Any]] = []
        while True:
            self._refresh_lock(owner)
            page = self._table.query(**kwargs)
            for row in page.get("Items", []):
                if _key_time(row) >= cutoff:
                    continue
                chunk.append(row)
                if len(chunk) == _CHUNK_SIZE:
                    item_count, object_count = self._archive_rows(chunk)
                    archived += item_count
                    objects += object_count
                    chunk = []
            last = page.get("LastEvaluatedKey")
            if not last:
                break
            kwargs["ExclusiveStartKey"] = last
        if chunk:
            item_count, object_count = self._archive_rows(chunk)
            archived += item_count
            objects += object_count
        return archived, objects

    def _save_archive_cursor(self, day: str, owner: str) -> None:
        self._table.update_item(
            Key={"partition": _LOCK_PARTITION, "log_id": _LOCK_ID},
            UpdateExpression="SET archive_through_day = :day",
            ConditionExpression="lock_owner = :owner",
            ExpressionAttributeValues={":owner": owner, ":day": day},
        )

    def _archive_recent_overflow(
        self, cutoff: datetime, max_hot_items: int, owner: str
    ) -> tuple[int, int, int]:
        retained: deque[dict[str, Any]] = deque()
        overflow: list[dict[str, Any]] = []
        recent_items = archived_items = archive_objects = 0
        current = cutoff.date()
        final_day = datetime.now(UTC).date()
        while current <= final_day:
            day = current.isoformat()
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("partition").eq(day),
                "ScanIndexForward": True,
            }
            while True:
                self._refresh_lock(owner)
                page = self._table.query(**kwargs)
                for row in page.get("Items", []):
                    if row.get("partition") != day or _key_time(row) < cutoff:
                        continue
                    recent_items += 1
                    retained.append(row)
                    if len(retained) > max_hot_items:
                        overflow.append(retained.popleft())
                    if len(overflow) == _CHUNK_SIZE:
                        item_count, object_count = self._archive_rows(overflow)
                        archived_items += item_count
                        archive_objects += object_count
                        overflow = []
                last = page.get("LastEvaluatedKey")
                if not last:
                    break
                kwargs["ExclusiveStartKey"] = last
            current += timedelta(days=1)
        if overflow:
            item_count, object_count = self._archive_rows(overflow)
            archived_items += item_count
            archive_objects += object_count
        return recent_items, archived_items, archive_objects

    def _query_day(self, day: str, *, owner: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("partition").eq(day)}
        rows: list[dict[str, Any]] = []
        while True:
            if owner is not None:
                self._refresh_lock(owner)
            page = self._table.query(**kwargs)
            rows.extend(
                row for row in page.get("Items", []) if str(row.get("partition")) == day
            )
            last = page.get("LastEvaluatedKey")
            if not last:
                return rows
            kwargs["ExclusiveStartKey"] = last

    def _archive_rows(self, rows: list[dict[str, Any]]) -> tuple[int, int]:
        if not rows:
            return 0, 0
        rows.sort(key=_key_tuple)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row["partition"]), []).append(row)
        for day, day_rows in grouped.items():
            self._put_archive_object(day, day_rows)
        with self._table.batch_writer() as batch:
            for row in rows:
                batch.delete_item(
                    Key={"partition": row["partition"], "log_id": row["log_id"]}
                )
        return len(rows), len(grouped)

    def _put_archive_object(self, day: str, rows: list[dict[str, Any]]) -> str:
        body = b"".join(
            json.dumps(
                row,
                separators=(",", ":"),
                sort_keys=True,
                default=_json_default,
            ).encode()
            + b"\n"
            for row in rows
        )
        compressed = gzip.compress(body, mtime=0)
        digest = hashlib.sha256(compressed).hexdigest()
        key = f"{ARCHIVE_PREFIX}/date={day}/part-{digest}.jsonl.gz"
        with suppress_audit_collection():
            self._storage.put_bytes(key, compressed, "application/gzip")
        return key

    def _compact_archive_day(self, day: str, owner: str) -> int:
        prefix = f"{ARCHIVE_PREFIX}/date={day}/"
        objects = self._storage.list_objects(prefix=prefix)
        if (
            len(objects) <= 20
            or min(obj.size for obj in objects) >= _COMPACT_OBJECT_MIN_BYTES
        ):
            return 0
        rows_by_id: dict[str, dict[str, Any]] = {}
        for offset, obj in enumerate(objects):
            if offset % 100 == 0:
                self._refresh_lock(owner)
            for line in gzip.decompress(self._storage.get_bytes(obj.key)).splitlines():
                if line:
                    row = json.loads(line)
                    rows_by_id[str(row["log_id"])] = row
        ordered = sorted(rows_by_id.values(), key=lambda row: str(row["log_id"]))
        compacted_keys = {
            self._put_archive_object(day, ordered[offset : offset + _CHUNK_SIZE])
            for offset in range(0, len(ordered), _CHUNK_SIZE)
        }
        obsolete = [obj.key for obj in objects if obj.key not in compacted_keys]
        if obsolete:
            with suppress_audit_collection():
                self._storage.delete_many(obsolete)
            record_audit(
                "audit_log_archive.compacted",
                "audit_log_archive_day",
                f"{day}:{len(objects)}->{len(compacted_keys)}",
            )
        return len(compacted_keys)

    def _acquire_lock(self) -> str | None:
        owner = str(uuid4())
        now = int(datetime.now(UTC).timestamp())
        try:
            self._table.update_item(
                Key={"partition": _LOCK_PARTITION, "log_id": _LOCK_ID},
                UpdateExpression="SET lock_owner = :owner, lock_expires_at = :expires",
                ConditionExpression="attribute_not_exists(#partition) OR lock_expires_at <= :now",
                ExpressionAttributeNames={"#partition": "partition"},
                ExpressionAttributeValues={
                    ":owner": owner,
                    ":now": now,
                    ":expires": now + _LOCK_SECONDS,
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return owner

    def _release_lock(self, owner: str) -> None:
        try:
            self._table.update_item(
                Key={"partition": _LOCK_PARTITION, "log_id": _LOCK_ID},
                UpdateExpression="SET lock_expires_at = :now REMOVE lock_owner",
                ConditionExpression="lock_owner = :owner",
                ExpressionAttributeValues={
                    ":owner": owner,
                    ":now": int(datetime.now(UTC).timestamp()),
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def _refresh_lock(self, owner: str) -> None:
        now = int(datetime.now(UTC).timestamp())
        self._table.update_item(
            Key={"partition": _LOCK_PARTITION, "log_id": _LOCK_ID},
            UpdateExpression="SET lock_expires_at = :expires",
            ConditionExpression="lock_owner = :owner",
            ExpressionAttributeValues={
                ":owner": owner,
                ":expires": now + _LOCK_SECONDS,
            },
        )


def _key_tuple(key: dict[str, str]) -> tuple[str, str]:
    return key["partition"], key["log_id"]


def _key_time(key: dict[str, str]) -> datetime:
    timestamp = key["log_id"].split("#", 1)[0]
    parsed = datetime.fromisoformat(timestamp)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Unsupported audit value: {type(value).__name__}")

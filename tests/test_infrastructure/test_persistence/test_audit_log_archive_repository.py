from __future__ import annotations

import gzip
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from src.application.ports.object_storage_port import ObjectInfo, ObjectStorageRef
from src.infrastructure.persistence.database.dynamodb.repositories.audit_log_archive_repository import (
    DynamoAuditLogArchiveRepository,
)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_bytes(
        self, key: str, content: bytes, content_type: str = ""
    ) -> ObjectStorageRef:
        self.objects[key] = content
        return ObjectStorageRef("bucket", key, f"s3://bucket/{key}")

    def list_objects(self, prefix: str = "") -> list[ObjectInfo]:
        return [
            ObjectInfo(key, len(value), datetime.now(UTC))
            for key, value in self.objects.items()
            if key.startswith(prefix)
        ]

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


class MemoryTable:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.deleted: list[dict[str, str]] = []
        self.lock_item: dict[str, Any] | None = None
        self.scan_count = 0

    def get_item(self, **_: Any) -> dict[str, Any]:
        return {"Item": self.lock_item} if self.lock_item else {}

    def update_item(self, **kwargs: Any) -> None:
        values = kwargs["ExpressionAttributeValues"]
        expression = kwargs["UpdateExpression"]
        if self.lock_item is None:
            key = kwargs["Key"]
            self.lock_item = {**key}
        if "archive_through_day" in expression:
            self.lock_item["archive_through_day"] = values[":day"]
        elif "REMOVE lock_owner" in expression:
            self.lock_item.pop("lock_owner", None)
            self.lock_item["lock_expires_at"] = values[":now"]
        else:
            if "SET lock_owner" in expression:
                self.lock_item["lock_owner"] = values[":owner"]
            expiration = values.get(":expires", values.get(":expiry"))
            if expiration is not None:
                self.lock_item["lock_expires_at"] = expiration

    def delete_item(self, *, Key: dict[str, str], **_: Any) -> None:
        if Key["partition"] != "_aria_audit_archive":
            key = (Key["partition"], Key["log_id"])
            self.rows[:] = [
                row for row in self.rows if (row["partition"], row["log_id"]) != key
            ]

    def scan(self, **_: Any) -> dict[str, Any]:
        self.scan_count += 1
        return {"Items": list(self.rows)}

    @contextmanager
    def batch_writer(self):
        class Writer:
            def __init__(self, target: MemoryTable) -> None:
                self.target = target

            def delete_item(self, *, Key: dict[str, str]) -> None:
                self.target.deleted.append(Key)
                self.target.delete_item(Key=Key)

        yield Writer(self)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        expression = kwargs["KeyConditionExpression"].get_expression()
        day = expression["values"][1]
        rows = sorted(
            [row for row in self.rows if row["partition"] == day],
            key=lambda row: (row["partition"], row["log_id"]),
            reverse=not kwargs.get("ScanIndexForward", True),
        )
        return {"Items": list(rows)}


def _row(days_ago: int, suffix: str) -> dict[str, str]:
    occurred = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "partition": occurred.date().isoformat(),
        "log_id": f"{occurred.isoformat()}#{suffix}",
        "tipo": "dynamodb.PutItem",
        "actor_id": "analyst-1",
    }


def test_flush_archives_old_and_excess_rows_before_deleting() -> None:
    rows = [_row(8, "old"), _row(2, "middle"), _row(1, "new")]
    table = MemoryTable(rows)
    storage = MemoryStorage()
    repository = DynamoAuditLogArchiveRepository(storage, table=table)

    result = repository.flush(max_hot_items=1, retention_days=5)

    assert result == {
        "busy": 0,
        "hot_items_before": 3,
        "archived_items": 2,
        "deleted_items": 2,
        "archive_objects": 2,
        "hot_items_after_estimate": 1,
    }
    assert len(table.deleted) == 2
    assert table.lock_item is not None
    assert "lock_owner" not in table.lock_item
    assert table.lock_item["archive_through_day"]
    assert len(storage.objects) == 2
    second_result = repository.flush(max_hot_items=1, retention_days=5)
    assert second_result["archived_items"] == 0
    assert table.scan_count == 1
    archived = [
        json.loads(line)
        for value in storage.objects.values()
        for line in gzip.decompress(value).splitlines()
    ]
    assert {row["actor_id"] for row in archived} == {"analyst-1"}


def test_query_combines_archived_objects_with_hot_rows() -> None:
    day = datetime.now(UTC).date().isoformat()
    archived_row = _row(0, "archived")
    archived_row["partition"] = day
    hot_row = _row(0, "hot")
    hot_row["partition"] = day
    storage = MemoryStorage()
    payload = gzip.compress((json.dumps(archived_row) + "\n").encode("utf-8"))
    key = f"audit-log-archive/date={day}/part-test.jsonl.gz"
    storage.put_bytes(key, payload)
    table = MemoryTable([hot_row])
    repository = DynamoAuditLogArchiveRepository(storage, table=table)

    result = repository.query(from_date=day, to_date=day, limit=10)

    assert {row["log_id"].split("#")[-1] for row in result} == {"archived", "hot"}


def test_compact_archive_day_reduces_many_small_objects(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "src.infrastructure.persistence.database.dynamodb.repositories."
        "audit_log_archive_repository.record_audit",
        lambda *_args, **_kwargs: None,
    )
    day = datetime.now(UTC).date().isoformat()
    storage = MemoryStorage()
    for index in range(21):
        row = _row(0, f"row-{index:02d}")
        row["partition"] = day
        storage.put_bytes(
            f"audit-log-archive/date={day}/part-{index}.jsonl.gz",
            gzip.compress((json.dumps(row) + "\n").encode()),
        )
    table = MemoryTable([])
    table.lock_item = {"lock_owner": "test-owner"}
    repository = DynamoAuditLogArchiveRepository(storage, table=table)

    compacted = repository._compact_archive_day(day, "test-owner")

    assert compacted == 1
    assert len(storage.objects) == 1
    archived_rows = [
        json.loads(line)
        for payload in storage.objects.values()
        for line in gzip.decompress(payload).splitlines()
    ]
    assert len(archived_rows) == 21

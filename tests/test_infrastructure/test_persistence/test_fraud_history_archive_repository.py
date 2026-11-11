from __future__ import annotations

import gzip
import hashlib
import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.application.ports.fraud_history_archive_index_port import (
    ArchiveIndexPort,
)
from src.application.ports.fraud_history_archive_port import (
    ArchiveIndexEntry,
    ArchiveVerificationError,
)
from src.application.ports.legal_hold_port import LegalHold
from src.application.ports.object_storage_port import ObjectStorageRef
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
    DynamoFraudHistoryArchiveRepository,
)

DAY = date(2025, 10, 26)


class InMemoryStorage:
    def __init__(self, *, corrupt_reads: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.corrupt_reads = corrupt_reads

    def put_bytes(
        self, key: str, content: bytes, content_type: str = ""
    ) -> ObjectStorageRef:
        self.objects[key] = content
        return ObjectStorageRef("bucket", key, f"s3://bucket/{key}")

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key] + (b"!" if self.corrupt_reads else b"")


class InMemoryArchiveIndex(ArchiveIndexPort):
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: dict[str, ArchiveIndexEntry] = {}
        self.fail = fail

    def put_many(self, entries: list[ArchiveIndexEntry]) -> None:
        if self.fail:
            raise ConnectionError("index unavailable")
        self.entries.update({entry.alert_id: entry for entry in entries})

    def get(self, alert_id: str) -> ArchiveIndexEntry | None:
        return self.entries.get(alert_id)


class InMemoryLegalHolds:
    def __init__(self, active: set[str] | None = None) -> None:
        self.active = set(active or ())
        # Holds that appear after the first lookup, like a hold placed mid-run.
        self.appear_later: set[str] = set()
        self.lookups = 0

    def active_ids(self, alert_ids) -> set[str]:
        self.lookups += 1
        if self.lookups > 1:
            self.active |= self.appear_later
        return self.active & set(alert_ids)

    def place(self, hold: LegalHold) -> bool:
        self.active.add(hold.alert_id)
        return True


class InMemoryTable:
    """Pages query results two items at a time to exercise pagination."""

    def __init__(self, rows: list[dict[str, Any]], key_names: tuple[str, str]) -> None:
        self.rows = rows
        self.key_names = key_names
        self.deleted: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        condition = kwargs["KeyConditionExpression"]
        name = condition.get_expression()["values"][0].name
        value = condition.get_expression()["values"][1]
        matching = [row for row in self.rows if row.get(name) == value]
        start = int(kwargs.get("ExclusiveStartKey", {}).get("offset", 0))
        page = matching[start : start + 2]
        response: dict[str, Any] = {"Items": page}
        if start + 2 < len(matching):
            response["LastEvaluatedKey"] = {"offset": start + 2}
        return response

    @contextmanager
    def batch_writer(self):
        table = self

        class Batch:
            def delete_item(self, *, Key: dict[str, Any]) -> None:
                table.deleted.append(Key)
                table.rows[:] = [
                    row
                    for row in table.rows
                    if tuple(row[k] for k in table.key_names)
                    != tuple(Key[k] for k in table.key_names)
                ]

        yield Batch()


def _alert(alert_id: str, **extra: Any) -> dict[str, Any]:
    return {
        "partition": "alert",
        "alert_id": alert_id,
        "event_id": f"EV-{alert_id}",
        "created_day": DAY.isoformat(),
        "created_at": f"{DAY.isoformat()}T12:00:00+00:00",
        "amount": Decimal("2400.50"),
        **extra,
    }


def _review(alert_id: str, n: int) -> dict[str, Any]:
    return {
        "alert_id": alert_id,
        "review_key": f"2026-01-0{n}#r{n}",
        "note": f"nota {n}",
    }


def _repository(
    alerts: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    storage: InMemoryStorage | None = None,
    index: InMemoryArchiveIndex | None = None,
    holds: InMemoryLegalHolds | None = None,
):
    alerts_table = InMemoryTable(alerts, ("partition", "alert_id"))
    reviews_table = InMemoryTable(reviews, ("alert_id", "review_key"))
    storage = storage or InMemoryStorage()
    repository = DynamoFraudHistoryArchiveRepository(
        storage,
        index=index or InMemoryArchiveIndex(),
        holds=holds or InMemoryLegalHolds(),
        alerts_table=alerts_table,
        reviews_table=reviews_table,
    )
    return repository, alerts_table, reviews_table, storage


def _lines(content: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in gzip.decompress(content).splitlines()]


def test_archives_alerts_with_their_reviews_then_deletes_them() -> None:
    alerts = [_alert(f"a{i}") for i in range(3)] + [
        {**_alert("other"), "created_day": "2025-10-27"}
    ]
    reviews = [_review("a0", 1), _review("a0", 2), _review("a2", 3)]
    repository, alerts_table, reviews_table, storage = _repository(alerts, reviews)

    result = repository.archive_day(DAY, dry_run=False)

    assert (result.alerts, result.reviews, result.deleted, result.held) == (3, 3, 3, 0)
    ((key, content),) = storage.objects.items()
    assert key == result.object_key
    assert (
        key == f"fraud-history-archive/created_day=2025-10-26/{result.sha256}.jsonl.gz"
    )
    assert hashlib.sha256(content).hexdigest() == result.sha256
    lines = _lines(content)
    assert [line["alert"]["alert_id"] for line in lines] == ["a0", "a1", "a2"]
    assert lines[0]["alert"]["amount"] == "2400.50"
    assert [r["note"] for r in lines[0]["fraud_label_reviews"]] == ["nota 1", "nota 2"]
    assert [row["alert_id"] for row in alerts_table.rows] == ["other"]
    assert reviews_table.rows == []


def test_legal_hold_keeps_the_alert_and_its_reviews_hot() -> None:
    alerts = [_alert("a0"), _alert("held", legal_hold=True)]
    reviews = [_review("held", 1)]
    repository, alerts_table, reviews_table, storage = _repository(alerts, reviews)

    result = repository.archive_day(DAY, dry_run=False)

    assert (result.alerts, result.held, result.deleted) == (1, 1, 1)
    assert [
        line["alert"]["alert_id"] for line in _lines(*storage.objects.values())
    ] == ["a0"]
    assert [row["alert_id"] for row in alerts_table.rows] == ["held"]
    assert reviews_table.rows == [_review("held", 1)]


def test_dry_run_reports_without_writing_or_deleting() -> None:
    repository, alerts_table, _, storage = _repository([_alert("a0")], [])

    result = repository.archive_day(DAY, dry_run=True)

    assert result.alerts == 1 and result.deleted == 0 and result.object_key
    assert storage.objects == {} and alerts_table.deleted == []


def test_a_failed_read_back_deletes_nothing() -> None:
    storage = InMemoryStorage(corrupt_reads=True)
    repository, alerts_table, reviews_table, _ = _repository(
        [_alert("a0")], [_review("a0", 1)], storage
    )

    with pytest.raises(ArchiveVerificationError):
        repository.archive_day(DAY, dry_run=False)
    assert alerts_table.deleted == [] and reviews_table.deleted == []


def test_rerun_of_an_archived_day_is_a_noop() -> None:
    repository, _, _, storage = _repository([_alert("a0")], [])
    repository.archive_day(DAY, dry_run=False)

    again = repository.archive_day(DAY, dry_run=False)

    assert (again.alerts, again.deleted, again.object_key) == (0, 0, None)
    assert len(storage.objects) == 1


def test_identical_content_maps_to_the_same_object_name() -> None:
    first, _, _, first_storage = _repository([_alert("a1"), _alert("a0")], [])
    second, _, _, second_storage = _repository([_alert("a0"), _alert("a1")], [])

    assert (
        first.archive_day(DAY, dry_run=False).object_key
        == second.archive_day(DAY, dry_run=False).object_key
    )
    assert first_storage.objects == second_storage.objects


def test_every_archived_alert_is_indexed_with_a_readable_byte_range() -> None:
    index = InMemoryArchiveIndex()
    repository, _, _, storage = _repository(
        [_alert(f"a{i}") for i in range(3)], [_review("a1", 1)], index=index
    )

    result = repository.archive_day(DAY, dry_run=False)

    (content,) = storage.objects.values()
    assert sorted(index.entries) == ["a0", "a1", "a2"]
    for alert_id, entry in index.entries.items():
        assert entry.object_key == result.object_key and entry.created_day == DAY
        member = content[entry.offset : entry.offset + entry.length]
        assert hashlib.sha256(member).hexdigest() == entry.record_sha256
        record = json.loads(gzip.decompress(member))
        assert record["alert"]["alert_id"] == alert_id
    assert [
        r["note"]
        for r in json.loads(
            gzip.decompress(
                content[
                    index.entries["a1"].offset : index.entries["a1"].offset
                    + index.entries["a1"].length
                ]
            )
        )["fraud_label_reviews"]
    ] == ["nota 1"]
    # The members are contiguous: together they are the whole object.
    assert sum(entry.length for entry in index.entries.values()) == len(content)


def test_a_failed_index_write_deletes_nothing() -> None:
    repository, alerts_table, reviews_table, _ = _repository(
        [_alert("a0")], [_review("a0", 1)], index=InMemoryArchiveIndex(fail=True)
    )

    with pytest.raises(ConnectionError):
        repository.archive_day(DAY, dry_run=False)
    assert alerts_table.deleted == [] and reviews_table.deleted == []


def test_an_active_legal_hold_keeps_the_alert_hot_and_unindexed() -> None:
    index = InMemoryArchiveIndex()
    repository, alerts_table, reviews_table, _ = _repository(
        [_alert("a0"), _alert("held")],
        [_review("held", 1)],
        index=index,
        holds=InMemoryLegalHolds({"held"}),
    )

    result = repository.archive_day(DAY, dry_run=False)

    assert (result.alerts, result.held, result.deleted) == (1, 1, 1)
    assert list(index.entries) == ["a0"]
    assert [row["alert_id"] for row in alerts_table.rows] == ["held"]
    assert reviews_table.rows == [_review("held", 1)]


def test_a_hold_placed_while_archiving_still_keeps_the_rows() -> None:
    holds = InMemoryLegalHolds()
    holds.appear_later = {"late"}
    repository, alerts_table, reviews_table, _ = _repository(
        [_alert("a0"), _alert("late")], [_review("late", 1)], holds=holds
    )

    result = repository.archive_day(DAY, dry_run=False)

    assert (result.held, result.deleted) == (1, 1)
    assert [row["alert_id"] for row in alerts_table.rows] == ["late"]
    assert reviews_table.rows == [_review("late", 1)]


def test_index_entries_carry_the_event_id_that_travels_between_systems() -> None:
    index = InMemoryArchiveIndex()
    repository, *_ = _repository([_alert("a0"), _alert("a1")], [], index=index)

    repository.archive_day(DAY, dry_run=False)

    assert {k: v.event_id for k, v in index.entries.items()} == {
        "a0": "EV-a0",
        "a1": "EV-a1",
    }

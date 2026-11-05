from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, date, datetime
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
from src.application.ports.object_storage_port import ObjectInfo, ObjectStorageRef
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_reader import (
    DynamoFraudHistoryArchiveReader,
    LegalHoldProtectedArchiveKeys,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
    _member,
)

DAY = date(2025, 10, 26)


class RecordingStorage:
    """Counts reads so tests can tell a range read from a whole-object read."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.whole_reads = 0
        self.range_reads: list[tuple[str, int, int]] = []

    def put_bytes(
        self, key: str, content: bytes, content_type: str = ""
    ) -> ObjectStorageRef:
        self.objects[key] = content
        return ObjectStorageRef("bucket", key, key)

    def get_bytes(self, key: str) -> bytes:
        self.whole_reads += 1
        return self.objects[key]

    def get_range(self, key: str, offset: int, length: int) -> bytes:
        self.range_reads.append((key, offset, length))
        return self.objects[key][offset : offset + length]

    def list_objects(self, prefix: str = "") -> list[ObjectInfo]:
        return [
            ObjectInfo(key, len(data), datetime(2025, 1, 1, tzinfo=UTC))
            for key, data in sorted(self.objects.items())
            if key.startswith(prefix)
        ]


class InMemoryArchiveIndex(ArchiveIndexPort):
    def __init__(self) -> None:
        self.entries: dict[str, ArchiveIndexEntry] = {}

    def put_many(self, entries: list[ArchiveIndexEntry]) -> None:
        self.entries.update({entry.alert_id: entry for entry in entries})

    def get(self, alert_id: str) -> ArchiveIndexEntry | None:
        return self.entries.get(alert_id)

    def find_by_event_id(self, event_id: str) -> list[ArchiveIndexEntry]:
        return [e for e in self.entries.values() if e.event_id == event_id]

    def list_day(self, created_day: date, limit: int) -> list[ArchiveIndexEntry]:
        return [e for e in self.entries.values() if e.created_day == created_day][:limit]


def _record(alert_id: str) -> dict[str, Any]:
    return {
        "alert": {"alert_id": alert_id, "event_id": f"EV-{alert_id}", "amount": "10.50"},
        "fraud_label_reviews": [{"alert_id": alert_id, "note": f"nota {alert_id}"}],
    }


def _store_new_format(
    storage: RecordingStorage, index: InMemoryArchiveIndex, ids: list[str]
):
    members = [_member(_record(alert_id)) for alert_id in ids]
    data = b"".join(members)
    key = f"fraud-history-archive/created_day={DAY}/{hashlib.sha256(data).hexdigest()}.jsonl.gz"
    storage.put_bytes(key, data)
    offset = 0
    for alert_id, member in zip(ids, members, strict=True):
        index.put_many(
            [
                ArchiveIndexEntry(
                    alert_id,
                    DAY,
                    key,
                    offset,
                    len(member),
                    hashlib.sha256(member).hexdigest(),
                )
            ]
        )
        offset += len(member)
    return key


def _legacy_object(storage: RecordingStorage, ids: list[str]) -> str:
    """The pre-index format: ONE gzip stream holding every line of the day."""
    lines = b"".join(
        json.dumps(_record(alert_id), separators=(",", ":"), sort_keys=True).encode()
        + b"\n"
        for alert_id in ids
    )
    data = gzip.compress(lines, mtime=0)
    key = f"fraud-history-archive/created_day={DAY}/{hashlib.sha256(data).hexdigest()}.jsonl.gz"
    storage.put_bytes(key, data)
    return key


def test_reads_one_alert_with_a_single_range_request_and_its_reviews() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    key = _store_new_format(storage, index, ["a0", "a1", "a2"])
    reader = DynamoFraudHistoryArchiveReader(storage, index)

    archived = reader.get_archived_alert("a1")

    assert archived is not None
    assert archived.alert == {"alert_id": "a1", "event_id": "EV-a1", "amount": "10.50"}
    assert archived.fraud_label_reviews == [{"alert_id": "a1", "note": "nota a1"}]
    assert (archived.created_day, archived.object_key) == (DAY, key)
    assert archived.verified_against == "record"
    assert storage.whole_reads == 0 and len(storage.range_reads) == 1


def test_an_unknown_alert_is_none() -> None:
    reader = DynamoFraudHistoryArchiveReader(RecordingStorage(), InMemoryArchiveIndex())

    assert reader.get_archived_alert("nope") is None
    assert reader.is_archived("nope") is False


def test_a_tampered_record_is_never_served() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    key = _store_new_format(storage, index, ["a0", "a1"])
    entry = index.get("a1")
    storage.objects[key] = (
        storage.objects[key][: entry.offset]
        + _member(_record("evil"))[: entry.length].ljust(entry.length, b"\0")
        + storage.objects[key][entry.offset + entry.length :]
    )
    reader = DynamoFraudHistoryArchiveReader(storage, index)

    with pytest.raises(ArchiveVerificationError):
        reader.get_archived_alert("a1")


def test_a_legacy_whole_day_object_is_read_whole_and_checked_by_its_name() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    key = _legacy_object(storage, ["a0", "a1"])
    index.put_many([ArchiveIndexEntry("a1", DAY, key)])
    reader = DynamoFraudHistoryArchiveReader(storage, index)

    archived = reader.get_archived_alert("a1")

    assert archived is not None and archived.alert["alert_id"] == "a1"
    assert archived.verified_against == "object"
    assert storage.whole_reads == 1 and storage.range_reads == []


def test_a_legacy_object_that_no_longer_matches_its_name_is_refused() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    key = _legacy_object(storage, ["a0"])
    storage.objects[key] += b"x"
    index.put_many([ArchiveIndexEntry("a0", DAY, key)])

    with pytest.raises(ArchiveVerificationError):
        DynamoFraudHistoryArchiveReader(storage, index).get_archived_alert("a0")


def test_backfill_indexes_legacy_and_new_objects_and_is_idempotent() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    legacy = _legacy_object(storage, ["l0", "l1"])
    # A second, new-format object for another day.
    members = [_member(_record(i)) for i in ("n0", "n1")]
    data = b"".join(members)
    new_key = f"fraud-history-archive/created_day=2025-10-27/{hashlib.sha256(data).hexdigest()}.jsonl.gz"
    storage.put_bytes(new_key, data)
    reader = DynamoFraudHistoryArchiveReader(storage, index)

    dry = reader.backfill_index(dry_run=True)
    assert (dry.objects, dry.alerts, dry.indexed) == (2, 4, 4) and index.entries == {}

    applied = reader.backfill_index(dry_run=False)
    assert (applied.indexed, applied.already_indexed) == (4, 0)
    assert index.get("l0").object_key == legacy and index.get("l0").offset is None
    assert index.get("n1").offset == len(members[0])
    assert index.get("n1").length == len(members[1])
    assert index.get("n1").created_day == date(2025, 10, 27)
    # Every backfilled alert is readable, whichever way it was stored.
    assert reader.get_archived_alert("l1").alert["alert_id"] == "l1"
    assert reader.get_archived_alert("n0").alert["alert_id"] == "n0"

    again = reader.backfill_index(dry_run=False)
    assert (again.indexed, again.already_indexed) == (0, 4)


class InMemoryLegalHolds:
    def __init__(self, active: list[str]) -> None:
        self.active = active

    def list_active(self, limit: int = 100) -> list[LegalHold]:
        return [
            LegalHold(
                alert_id, "motivo del caso", None, "u", datetime(2026, 1, 1, tzinfo=UTC)
            )
            for alert_id in self.active
        ]


def test_protected_keys_are_the_day_objects_of_alerts_under_hold() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    held_key = _store_new_format(storage, index, ["a0", "a1"])
    index.put_many([ArchiveIndexEntry("hot-only", DAY, "never-archived")])
    holds = InMemoryLegalHolds(["a1", "not-archived"])

    keys = LegalHoldProtectedArchiveKeys(holds, index).protected_object_keys()

    assert keys == frozenset({held_key})


def test_backfill_records_the_event_id_and_search_finds_by_each_criterion() -> None:
    storage, index = RecordingStorage(), InMemoryArchiveIndex()
    _legacy_object(storage, ["l0", "l1"])
    reader = DynamoFraudHistoryArchiveReader(storage, index)
    reader.backfill_index(dry_run=False)

    by_id = reader.search(alert_id="l0")
    by_event = reader.search(event_id="EV-l1")
    by_day = reader.search(created_day=DAY)

    assert [(h.alert_id, h.event_id, h.created_day) for h in by_id] == [("l0", "EV-l0", DAY)]
    assert [h.alert_id for h in by_event] == ["l1"]
    assert sorted(h.alert_id for h in by_day) == ["l0", "l1"]
    assert reader.search(event_id="nope") == [] and reader.search(alert_id="nope") == []
    assert reader.search(created_day=DAY, limit=1) != by_day
    with pytest.raises(ValueError):
        reader.search()

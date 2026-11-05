"""Reads single alerts back from the cold fraud-history archive (#11c).

The index says which day object holds an alert and, for objects written with
per-alert gzip members, the byte range of that member: one range request and
a SHA-256 check of just those bytes. Objects from before the index (one gzip
stream per day) are read whole and checked against the digest in their name.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import zlib
from collections.abc import Iterator
from datetime import date
from typing import Any

from src.application.ports.fraud_history_archive_index_port import (
    ArchiveIndexPort,
)
from src.application.ports.fraud_history_archive_port import (
    ArchivedAlert,
    ArchivedAlertSummary,
    ArchiveIndexBackfillResult,
    ArchiveIndexEntry,
    ArchiveVerificationError,
)
from src.application.ports.fraud_history_archive_reader_port import (
    FraudHistoryArchiveReaderPort,
)
from src.application.ports.legal_hold_port import LegalHoldRepository
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.ports.protected_object_keys_port import (
    ProtectedObjectKeysPort,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
    ARCHIVE_PREFIX,
)


class DynamoFraudHistoryArchiveReader(FraudHistoryArchiveReaderPort):
    def __init__(self, storage: ObjectStoragePort, index: ArchiveIndexPort) -> None:
        self._storage = storage
        self._index = index

    def is_archived(self, alert_id: str) -> bool:
        return self._index.get(alert_id) is not None

    def get_archived_alert(self, alert_id: str) -> ArchivedAlert | None:
        entry = self._index.get(alert_id)
        if entry is None:
            return None
        if entry.offset is not None and entry.length is not None:
            member = self._storage.get_range(
                entry.object_key, entry.offset, entry.length
            )
            if (
                entry.record_sha256
                and hashlib.sha256(member).hexdigest() != entry.record_sha256
            ):
                raise ArchiveVerificationError(
                    f"archived alert {alert_id} does not match its recorded digest"
                )
            record = _record_with(gzip.decompress(member), alert_id)
            against = "record"
        else:
            data = self._storage.get_bytes(entry.object_key)
            if hashlib.sha256(data).hexdigest() != _digest_in_name(entry.object_key):
                raise ArchiveVerificationError(
                    f"archive {entry.object_key} does not match its digest"
                )
            record = _record_with(gzip.decompress(data), alert_id)
            against = "object"
        if record is None:
            raise ArchiveVerificationError(
                f"archive {entry.object_key} does not contain alert {alert_id}"
            )
        return ArchivedAlert(
            alert_id=alert_id,
            created_day=entry.created_day,
            object_key=entry.object_key,
            alert=record["alert"],
            fraud_label_reviews=record.get("fraud_label_reviews", []),
            verified_against=against,
        )

    def search(
        self,
        *,
        alert_id: str | None = None,
        event_id: str | None = None,
        created_day: date | None = None,
        limit: int = 100,
    ) -> list[ArchivedAlertSummary]:
        if alert_id:
            entry = self._index.get(alert_id)
            entries = [entry] if entry else []
        elif event_id:
            entries = self._index.find_by_event_id(event_id)
        elif created_day:
            entries = self._index.list_day(created_day, limit)
        else:
            raise ValueError("search needs alert_id, event_id or created_day")
        return [
            ArchivedAlertSummary(e.alert_id, e.event_id, e.created_day)
            for e in entries[:limit]
        ]

    def backfill_index(self, *, dry_run: bool) -> ArchiveIndexBackfillResult:
        objects = alerts = indexed = already = 0
        keys = sorted(
            obj.key
            for obj in self._storage.list_objects(f"{ARCHIVE_PREFIX}/")
            if obj.key.endswith(".jsonl.gz")
        )
        for key in keys:
            objects += 1
            data = self._storage.get_bytes(key)
            if hashlib.sha256(data).hexdigest() != _digest_in_name(key):
                raise ArchiveVerificationError(
                    f"archive {key} does not match its digest"
                )
            day = date.fromisoformat(key.split("created_day=", 1)[1].split("/", 1)[0])
            entries: list[ArchiveIndexEntry] = []
            for offset, length, member_records in _members(data):
                for alert_id, event_id in member_records:
                    alerts += 1
                    # An existing entry may point at a newer object (a re-run
                    # after a partial delete): the newest archive write owns it.
                    if self._index.get(alert_id) is not None:
                        already += 1
                        continue
                    single = len(member_records) == 1
                    entries.append(
                        ArchiveIndexEntry(
                            alert_id=alert_id,
                            created_day=day,
                            object_key=key,
                            offset=offset if single else None,
                            length=length if single else None,
                            record_sha256=(
                                hashlib.sha256(
                                    data[offset : offset + length]
                                ).hexdigest()
                                if single
                                else None
                            ),
                            event_id=event_id,
                        )
                    )
            indexed += len(entries)
            if entries and not dry_run:
                self._index.put_many(entries)
        return ArchiveIndexBackfillResult(objects, alerts, indexed, already)


def _digest_in_name(key: str) -> str:
    return key.rsplit("/", 1)[-1].split(".", 1)[0]


def _record_with(raw: bytes, alert_id: str) -> dict[str, Any] | None:
    for line in raw.splitlines():
        if not line:
            continue
        record = json.loads(line)
        if str(record["alert"]["alert_id"]) == alert_id:
            return record
    return None


def _members(
    data: bytes,
) -> Iterator[tuple[int, int, list[tuple[str, str | None]]]]:
    """(offset, length, [(alert_id, event_id)]) per gzip member of an object."""
    position = 0
    while position < len(data):
        decoder = zlib.decompressobj(wbits=31)
        raw = decoder.decompress(data[position:])
        length = len(data) - position - len(decoder.unused_data)
        alerts = [json.loads(line)["alert"] for line in raw.splitlines() if line]
        ids = [
            (str(a["alert_id"]), str(a["event_id"]) if a.get("event_id") else None)
            for a in alerts
        ]
        yield position, length, ids
        position += length


class LegalHoldProtectedArchiveKeys(ProtectedObjectKeysPort):
    """Archive day objects that contain an alert under legal hold."""

    def __init__(self, holds: LegalHoldRepository, index: ArchiveIndexPort) -> None:
        self._holds = holds
        self._index = index

    def protected_object_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hold in self._holds.list_active(limit=10_000):
            entry = self._index.get(hold.alert_id)
            if entry is not None:
                keys.add(entry.object_key)
        return frozenset(keys)

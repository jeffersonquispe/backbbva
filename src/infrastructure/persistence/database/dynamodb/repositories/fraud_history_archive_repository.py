"""Cold archive of the fraud history (FraudHistoryArchivePort).

One immutable gzip JSONL object per Bogotá creation day under
``fraud-history-archive/created_day=YYYY-MM-DD/``: one line per alert with
the full alert item and its fraud_label_reviews rows (labels, reviewer,
notes). Each line is its own gzip member (concatenated members are one valid
gzip file), so a single alert is readable with one range request, located
through the ``alert_id`` index. The object name is its SHA-256, so an
identical re-run overwrites nothing new; a re-run after a partial delete
writes a smaller object and a restore dedupes by alert_id. Rows are deleted
only after the object reads back with the same digest and every moved alert
is indexed. Each delete still goes through the audited DynamoDB client, so
the audit log records what retention removed."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.fraud_history_archive_index_port import (
    ArchiveIndexPort,
)
from src.application.ports.fraud_history_archive_port import (
    ArchiveIndexEntry,
    ArchiveVerificationError,
    FraudHistoryArchivePort,
    FraudHistoryDayArchive,
)
from src.application.ports.legal_hold_port import LegalHoldRepository
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.monitoring.audit_collector import suppress_audit_collection
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

ALERTS_TABLE_NAME = "alerts"
REVIEWS_TABLE_NAME = "fraud_label_reviews"
ARCHIVE_PREFIX = "fraud-history-archive"
CREATED_DAY_INDEX = "CreatedDayIdx"
# An alert with an active legal hold (LegalHoldRepository) is never archived or
# deleted. The attribute on the alert item is the older manual way to say the
# same and is still honoured.
LEGAL_HOLD_ATTRIBUTE = "legal_hold"


class DynamoFraudHistoryArchiveRepository(FraudHistoryArchivePort):
    def __init__(
        self,
        storage: ObjectStoragePort,
        *,
        index: ArchiveIndexPort,
        holds: LegalHoldRepository,
        alerts_table: Any | None = None,
        reviews_table: Any | None = None,
    ) -> None:
        self._alerts = (
            alerts_table
            if alerts_table is not None
            else get_dynamodb_resource().Table(ALERTS_TABLE_NAME)
        )
        self._reviews = (
            reviews_table
            if reviews_table is not None
            else get_dynamodb_resource().Table(REVIEWS_TABLE_NAME)
        )
        self._storage = storage
        self._index = index
        self._holds = holds

    def archive_day(
        self, created_day: date, *, dry_run: bool
    ) -> FraudHistoryDayArchive:
        alerts = self._alerts_of_day(created_day.isoformat())
        held_ids = self._holds.active_ids([str(a["alert_id"]) for a in alerts])
        held = [a for a in alerts if _is_held(a, held_ids)]
        movable = [a for a in alerts if not _is_held(a, held_ids)]
        movable.sort(key=lambda alert: str(alert["alert_id"]))
        records = [
            {"alert": alert, "fraud_label_reviews": self._reviews_of(alert["alert_id"])}
            for alert in movable
        ]
        reviews = sum(len(record["fraud_label_reviews"]) for record in records)
        if not records:
            return FraudHistoryDayArchive(created_day, 0, 0, len(held), 0, None, None)
        members = [_member(record) for record in records]
        compressed = b"".join(members)
        digest = hashlib.sha256(compressed).hexdigest()
        key = (
            f"{ARCHIVE_PREFIX}/created_day={created_day.isoformat()}/{digest}.jsonl.gz"
        )
        if dry_run:
            return FraudHistoryDayArchive(
                created_day, len(records), reviews, len(held), 0, key, digest
            )
        with suppress_audit_collection():
            self._storage.put_bytes(key, compressed, "application/gzip")
            stored = self._storage.get_bytes(key)
        if hashlib.sha256(stored).hexdigest() != digest:
            raise ArchiveVerificationError(f"archive {key} does not match its digest")
        offset = 0
        entries: list[ArchiveIndexEntry] = []
        for record, member in zip(records, members, strict=True):
            entries.append(
                ArchiveIndexEntry(
                    alert_id=str(record["alert"]["alert_id"]),
                    created_day=created_day,
                    object_key=key,
                    offset=offset,
                    length=len(member),
                    record_sha256=hashlib.sha256(member).hexdigest(),
                    event_id=_event_id(record["alert"]),
                )
            )
            offset += len(member)
        # Indexed before any row is deleted: an archived alert is never
        # unreachable, even if this run dies halfway through the deletes.
        self._index.put_many(entries)
        # A hold placed while the object was being written wins: keep those
        # rows hot (their copy in the object is harmless and deduped later).
        late_holds = self._holds.active_ids([e.alert_id for e in entries]) - held_ids
        movable = [a for a in movable if str(a["alert_id"]) not in late_holds]
        with self._reviews.batch_writer() as batch:
            for record in records:
                if str(record["alert"]["alert_id"]) in late_holds:
                    continue
                for review in record["fraud_label_reviews"]:
                    batch.delete_item(
                        Key={
                            "alert_id": review["alert_id"],
                            "review_key": review["review_key"],
                        }
                    )
        with self._alerts.batch_writer() as batch:
            for alert in movable:
                batch.delete_item(
                    Key={"partition": alert["partition"], "alert_id": alert["alert_id"]}
                )
        return FraudHistoryDayArchive(
            created_day,
            len(records),
            reviews,
            len(held) + len(late_holds),
            len(movable),
            key,
            digest,
        )

    def _alerts_of_day(self, day: str) -> list[dict[str, Any]]:
        return _query_all(
            self._alerts,
            IndexName=CREATED_DAY_INDEX,
            KeyConditionExpression=Key("created_day").eq(day),
        )

    def _reviews_of(self, alert_id: str) -> list[dict[str, Any]]:
        return _query_all(
            self._reviews,
            KeyConditionExpression=Key("alert_id").eq(alert_id),
            ConsistentRead=True,
        )


def _event_id(alert: dict[str, Any]) -> str | None:
    value = alert.get("event_id")
    return str(value) if value else None


def _is_held(alert: dict[str, Any], held_ids: set[str]) -> bool:
    return bool(alert.get(LEGAL_HOLD_ATTRIBUTE)) or str(alert["alert_id"]) in held_ids


def _member(record: dict[str, Any]) -> bytes:
    """One alert (plus its reviews) as its own deterministic gzip member."""
    line = (
        json.dumps(
            record, separators=(",", ":"), sort_keys=True, default=_json_default
        ).encode()
        + b"\n"
    )
    return gzip.compress(line, mtime=0)


def _query_all(table: Any, **kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        response = table.query(**kwargs)
        items.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


def _json_default(value: Any) -> Any:
    # Decimal keeps its exact text (amounts); sets come back as sorted lists.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, set | frozenset):
        return sorted(value, key=str)
    if isinstance(value, bytes | bytearray):
        return value.hex()
    raise TypeError(f"Unsupported archive value: {type(value).__name__}")

"""Cold archive of the fraud history (FraudHistoryArchivePort).

One immutable gzip JSONL object per Bogotá creation day under
``fraud-history-archive/created_day=YYYY-MM-DD/``: one line per alert with
the full alert item and its fraud_label_reviews rows (labels, reviewer,
notes). The object name is its SHA-256, so an identical re-run overwrites
nothing new; a re-run after a partial delete writes a smaller object and a
restore dedupes by alert_id. Rows are deleted only after the object reads
back with the same digest. Each delete still goes through the audited
DynamoDB client, so the audit log records what retention removed."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.fraud_history_archive_port import (
    FraudHistoryArchivePort,
    FraudHistoryDayArchive,
)
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.monitoring.audit_collector import suppress_audit_collection
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

ALERTS_TABLE_NAME = "alerts"
REVIEWS_TABLE_NAME = "fraud_label_reviews"
ARCHIVE_PREFIX = "fraud-history-archive"
CREATED_DAY_INDEX = "CreatedDayIdx"
# An alert item with a truthy legal_hold is never archived or deleted.
LEGAL_HOLD_ATTRIBUTE = "legal_hold"


class ArchiveVerificationError(RuntimeError):
    pass


class DynamoFraudHistoryArchiveRepository(FraudHistoryArchivePort):
    def __init__(
        self,
        storage: ObjectStoragePort,
        *,
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

    def archive_day(self, created_day: date, *, dry_run: bool) -> FraudHistoryDayArchive:
        alerts = self._alerts_of_day(created_day.isoformat())
        held = [alert for alert in alerts if alert.get(LEGAL_HOLD_ATTRIBUTE)]
        movable = [alert for alert in alerts if not alert.get(LEGAL_HOLD_ATTRIBUTE)]
        movable.sort(key=lambda alert: str(alert["alert_id"]))
        records = [
            {"alert": alert, "fraud_label_reviews": self._reviews_of(alert["alert_id"])}
            for alert in movable
        ]
        reviews = sum(len(record["fraud_label_reviews"]) for record in records)
        if not records:
            return FraudHistoryDayArchive(
                created_day, 0, 0, len(held), 0, None, None
            )
        compressed = gzip.compress(
            b"".join(
                json.dumps(
                    record, separators=(",", ":"), sort_keys=True, default=_json_default
                ).encode()
                + b"\n"
                for record in records
            ),
            mtime=0,
        )
        digest = hashlib.sha256(compressed).hexdigest()
        key = f"{ARCHIVE_PREFIX}/created_day={created_day.isoformat()}/{digest}.jsonl.gz"
        if dry_run:
            return FraudHistoryDayArchive(
                created_day, len(records), reviews, len(held), 0, key, digest
            )
        with suppress_audit_collection():
            self._storage.put_bytes(key, compressed, "application/gzip")
            stored = self._storage.get_bytes(key)
        if hashlib.sha256(stored).hexdigest() != digest:
            raise ArchiveVerificationError(f"archive {key} does not match its digest")
        with self._reviews.batch_writer() as batch:
            for record in records:
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
            created_day, len(records), reviews, len(held), len(movable), key, digest
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

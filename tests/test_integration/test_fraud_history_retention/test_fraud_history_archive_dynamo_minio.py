"""Docker-only integration of fraud-history retention against the real
DynamoDB Local (CreatedDayIdx GSI, paginated queries, batch deletes) and the
real MinIO (write, read-back digest). Throwaway tables and bucket keep the
running stack's alerts untouched."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

if not os.getenv("DYNAMO_ENDPOINT") or not os.getenv("OBJECT_STORAGE_ENDPOINT"):
    pytest.skip(
        "Requires DynamoDB Local and MinIO (set DYNAMO_ENDPOINT and "
        "OBJECT_STORAGE_ENDPOINT)",
        allow_module_level=True,
    )

from src.application.ports.clock_port import Clock
from src.application.use_cases.fraud_review.archive_fraud_history import (
    ArchiveFraudHistory,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
    DynamoFraudHistoryArchiveRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    FRAUD_LABEL_REVIEWS_TABLE,
)
from src.infrastructure.persistence.object_storage.minio.minio_object_storage_adapter import (
    MinioObjectStorageAdapter,
)

pytestmark = pytest.mark.docker_integration

# 12:00 UTC = 07:00 Bogotá, so today in Bogotá is 2026-10-27.
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HOT_DAYS = 365
# Newest archivable day: today - (HOT_DAYS + 1).
ARCHIVED_DAY = date(2025, 10, 26)
HOT_DAY = date(2025, 10, 27)
# Enough rows for a real batch delete (25-item batches) on one day.
ALERTS_ON_ARCHIVED_DAY = 60


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


@pytest.fixture
def tables() -> Iterator[tuple[object, object]]:
    suffix = uuid.uuid4().hex[:10]
    alerts_schema = {**ALERTS_TABLE, "TableName": f"it_alerts_{suffix}"}
    reviews_schema = {
        **FRAUD_LABEL_REVIEWS_TABLE,
        "TableName": f"it_fraud_label_reviews_{suffix}",
    }
    create_table(alerts_schema)
    create_table(reviews_schema)
    resource = get_dynamodb_resource()
    alerts = resource.Table(alerts_schema["TableName"])
    reviews = resource.Table(reviews_schema["TableName"])
    yield alerts, reviews
    alerts.delete()
    reviews.delete()


@pytest.fixture
def storage() -> Iterator[MinioObjectStorageAdapter]:
    adapter = MinioObjectStorageAdapter(bucket=f"fraud-history-it-{uuid.uuid4().hex[:12]}")
    yield adapter
    for obj in adapter.list_objects():
        adapter.delete(obj.key)
    adapter._client.delete_bucket(Bucket=adapter._bucket)


def _alert(alert_id: str, day: date, **extra: object) -> dict[str, object]:
    return {
        "partition": "alert",
        "alert_id": alert_id,
        "event_id": f"IT-{alert_id}",
        "created_day": day.isoformat(),
        "created_at": f"{day.isoformat()}T15:00:00+00:00",
        "status": "CLOSED",
        "input": {"amount_value": Decimal("2400.50"), "customer_id": "c-1"},
        **extra,
    }


def _seed(alerts, reviews) -> dict[str, list[str]]:
    archived = [f"a-{i:03d}" for i in range(ALERTS_ON_ARCHIVED_DAY)]
    with alerts.batch_writer() as batch:
        for alert_id in archived:
            batch.put_item(Item=_alert(alert_id, ARCHIVED_DAY))
        batch.put_item(Item=_alert("held", ARCHIVED_DAY, legal_hold=True))
        batch.put_item(Item=_alert("hot", HOT_DAY))
    with reviews.batch_writer() as batch:
        for alert_id in archived[:5] + ["held", "hot"]:
            for n in (1, 2):
                batch.put_item(
                    Item={
                        "alert_id": alert_id,
                        "review_key": f"2026-01-0{n}T00:00:00+00:00#{n}",
                        "to_label": "fraud",
                        "note": f"nota {alert_id} {n}",
                        "reviewed_by": "fraud_reviewer@aria.test",
                    }
                )
    return {"archived": archived}


def _use_case(alerts, reviews, storage) -> ArchiveFraudHistory:
    archive = DynamoFraudHistoryArchiveRepository(
        storage, alerts_table=alerts, reviews_table=reviews
    )
    return ArchiveFraudHistory(archive, FixedClock(), "America/Bogota")


def _alert_ids(table) -> set[str]:
    return {item["alert_id"] for item in table.scan(ConsistentRead=True)["Items"]}


def test_dry_run_reports_the_day_without_writing_or_deleting(tables, storage) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)

    output = _use_case(alerts, reviews, storage).execute(
        hot_days=HOT_DAYS, scan_days=2, dry_run=True
    )

    day = next(d for d in output.days if d.created_day == ARCHIVED_DAY)
    assert (day.alerts, day.held, day.reviews, day.deleted) == (
        ALERTS_ON_ARCHIVED_DAY,
        1,
        10,
        0,
    )
    assert storage.list_objects() == []
    assert len(_alert_ids(alerts)) == ALERTS_ON_ARCHIVED_DAY + 2


def test_archives_verifies_and_deletes_then_reruns_as_noop(tables, storage) -> None:
    alerts, reviews = tables
    seeded = _seed(alerts, reviews)
    use_case = _use_case(alerts, reviews, storage)

    output = use_case.execute(hot_days=HOT_DAYS, scan_days=2, dry_run=False)

    day = next(d for d in output.days if d.created_day == ARCHIVED_DAY)
    assert (day.alerts, day.held, day.reviews, day.deleted) == (
        ALERTS_ON_ARCHIVED_DAY,
        1,
        10,
        ALERTS_ON_ARCHIVED_DAY,
    )
    (stored,) = storage.list_objects()
    assert stored.key == day.object_key
    assert stored.key.startswith("fraud-history-archive/created_day=2025-10-26/")
    content = storage.get_bytes(stored.key)
    assert hashlib.sha256(content).hexdigest() == day.sha256
    lines = [json.loads(line) for line in gzip.decompress(content).splitlines()]
    assert [line["alert"]["alert_id"] for line in lines] == seeded["archived"]
    assert lines[0]["alert"]["input"]["amount_value"] == "2400.50"
    assert [r["note"] for r in lines[0]["fraud_label_reviews"]] == [
        "nota a-000 1",
        "nota a-000 2",
    ]
    # The day outside the window and the legal hold stay hot with their reviews.
    assert _alert_ids(alerts) == {"held", "hot"}
    assert _alert_ids(reviews) == {"held", "hot"}

    again = use_case.execute(hot_days=HOT_DAYS, scan_days=2, dry_run=False)

    assert again.alerts == 0 and again.deleted == 0
    assert len(storage.list_objects()) == 1
    assert _alert_ids(alerts) == {"held", "hot"}


def test_the_archive_window_never_reaches_the_hot_day(tables, storage) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)

    output = _use_case(alerts, reviews, storage).execute(
        hot_days=HOT_DAYS, scan_days=5, dry_run=False
    )

    assert max(d.created_day for d in output.days) == ARCHIVED_DAY
    assert "hot" in _alert_ids(alerts)
    # today - HOT_DAYS is the oldest day still kept hot.
    assert NOW.date() - timedelta(days=HOT_DAYS) == HOT_DAY

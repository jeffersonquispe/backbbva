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
from src.application.ports.legal_hold_port import LegalHold
from src.application.use_cases.fraud_review.archive_fraud_history import (
    ArchiveFraudHistory,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_index_repository import (
    DynamoFraudHistoryArchiveIndex,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_reader import (
    DynamoFraudHistoryArchiveReader,
    LegalHoldProtectedArchiveKeys,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
    DynamoFraudHistoryArchiveRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.legal_hold_repository import (
    DynamoLegalHoldRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    FRAUD_HISTORY_ARCHIVE_INDEX_TABLE,
    FRAUD_LABEL_REVIEWS_TABLE,
    LEGAL_HOLDS_TABLE,
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
def index_and_holds() -> (
    Iterator[tuple[DynamoFraudHistoryArchiveIndex, DynamoLegalHoldRepository]]
):
    suffix = uuid.uuid4().hex[:10]
    index_schema = {
        **FRAUD_HISTORY_ARCHIVE_INDEX_TABLE,
        "TableName": f"it_archive_index_{suffix}",
    }
    holds_schema = {**LEGAL_HOLDS_TABLE, "TableName": f"it_legal_holds_{suffix}"}
    create_table(index_schema)
    create_table(holds_schema)
    resource = get_dynamodb_resource()
    index_table = resource.Table(index_schema["TableName"])
    holds_table = resource.Table(holds_schema["TableName"])
    yield (
        DynamoFraudHistoryArchiveIndex(index_table),
        DynamoLegalHoldRepository(holds_table, resource=resource),
    )
    index_table.delete()
    holds_table.delete()


@pytest.fixture
def storage() -> Iterator[MinioObjectStorageAdapter]:
    adapter = MinioObjectStorageAdapter(
        bucket=f"fraud-history-it-{uuid.uuid4().hex[:12]}"
    )
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


def _use_case(alerts, reviews, storage, index_and_holds) -> ArchiveFraudHistory:
    index, holds = index_and_holds
    archive = DynamoFraudHistoryArchiveRepository(
        storage, index=index, holds=holds, alerts_table=alerts, reviews_table=reviews
    )
    return ArchiveFraudHistory(archive, FixedClock(), "America/Bogota")


def _alert_ids(table) -> set[str]:
    return {item["alert_id"] for item in table.scan(ConsistentRead=True)["Items"]}


def test_dry_run_reports_the_day_without_writing_or_deleting(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)

    output = _use_case(alerts, reviews, storage, index_and_holds).execute(
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


def test_archives_verifies_and_deletes_then_reruns_as_noop(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    seeded = _seed(alerts, reviews)
    use_case = _use_case(alerts, reviews, storage, index_and_holds)

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


def test_the_archive_window_never_reaches_the_hot_day(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)

    output = _use_case(alerts, reviews, storage, index_and_holds).execute(
        hot_days=HOT_DAYS, scan_days=5, dry_run=False
    )

    assert max(d.created_day for d in output.days) == ARCHIVED_DAY
    assert "hot" in _alert_ids(alerts)
    # today - HOT_DAYS is the oldest day still kept hot.
    assert NOW.date() - timedelta(days=HOT_DAYS) == HOT_DAY


def test_an_archived_alert_is_read_by_id_with_one_range_request(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)
    index, _ = index_and_holds
    day = next(
        d
        for d in _use_case(alerts, reviews, storage, index_and_holds)
        .execute(hot_days=HOT_DAYS, scan_days=2, dry_run=False)
        .days
        if d.created_day == ARCHIVED_DAY
    )
    reader = DynamoFraudHistoryArchiveReader(storage, index)

    archived = reader.get_archived_alert("a-003")

    assert archived is not None
    assert (
        archived.object_key == day.object_key and archived.verified_against == "record"
    )
    assert archived.alert["input"]["amount_value"] == "2400.50"
    assert [r["note"] for r in archived.fraud_label_reviews] == [
        "nota a-003 1",
        "nota a-003 2",
    ]
    entry = index.get("a-003")
    assert (
        storage.get_range(day.object_key, entry.offset, entry.length)
        == storage.get_bytes(day.object_key)[entry.offset : entry.offset + entry.length]
    )
    # Alerts that stayed hot, or never existed, are not in the archive.
    assert reader.get_archived_alert("hot") is None
    assert reader.get_archived_alert("held") is None


def test_a_hold_placed_in_the_holds_table_keeps_the_alert_hot(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)
    index, holds = index_and_holds
    assert holds.place(
        LegalHold("a-010", "Requerimiento judicial 123", "CASO-1", "u1", NOW)
    )
    assert (
        holds.place(LegalHold("a-010", "otro motivo largo", None, "u2", NOW)) is False
    )

    output = _use_case(alerts, reviews, storage, index_and_holds).execute(
        hot_days=HOT_DAYS, scan_days=2, dry_run=False
    )

    day = next(d for d in output.days if d.created_day == ARCHIVED_DAY)
    assert (day.held, day.deleted) == (2, ALERTS_ON_ARCHIVED_DAY - 1)
    assert _alert_ids(alerts) == {"held", "hot", "a-010"}
    assert index.get("a-010") is None and index.get("a-011") is not None

    released = holds.release(
        "a-010",
        released_by="u1",
        release_reason="Oficio de levantamiento",
        released_at=NOW,
    )
    assert released is not None and not released.active
    assert holds.active_ids(["a-010", "a-011"]) == set()
    # Once released, the next run archives it.
    again = _use_case(alerts, reviews, storage, index_and_holds).execute(
        hot_days=HOT_DAYS, scan_days=2, dry_run=False
    )
    assert next(d for d in again.days if d.created_day == ARCHIVED_DAY).deleted == 1
    assert _alert_ids(alerts) == {"held", "hot"}
    assert holds.place(LegalHold("a-010", "Nuevo requerimiento 456", None, "u3", NOW))
    assert [h.alert_id for h in holds.list_active()] == ["a-010"]


def test_a_hold_on_an_archived_alert_protects_its_day_object(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)
    index, holds = index_and_holds
    day = next(
        d
        for d in _use_case(alerts, reviews, storage, index_and_holds)
        .execute(hot_days=HOT_DAYS, scan_days=2, dry_run=False)
        .days
        if d.created_day == ARCHIVED_DAY
    )
    protected = LegalHoldProtectedArchiveKeys(holds, index)
    assert protected.protected_object_keys() == frozenset()

    holds.place(LegalHold("a-004", "Requerimiento judicial 123", None, "u1", NOW))

    assert protected.protected_object_keys() == frozenset({day.object_key})


def test_archived_alerts_are_found_by_event_id_and_by_day_through_the_real_indexes(
    tables, storage, index_and_holds
) -> None:
    alerts, reviews = tables
    _seed(alerts, reviews)
    index, _ = index_and_holds
    _use_case(alerts, reviews, storage, index_and_holds).execute(
        hot_days=HOT_DAYS, scan_days=2, dry_run=False
    )
    reader = DynamoFraudHistoryArchiveReader(storage, index)

    by_event = reader.search(event_id="IT-a-007")
    by_day = reader.search(created_day=ARCHIVED_DAY, limit=200)

    assert [(h.alert_id, h.event_id) for h in by_event] == [("a-007", "IT-a-007")]
    assert len(by_day) == ALERTS_ON_ARCHIVED_DAY
    assert len(reader.search(created_day=ARCHIVED_DAY, limit=10)) == 10
    assert reader.search(created_day=HOT_DAY) == [] and reader.search(event_id="IT-hot") == []

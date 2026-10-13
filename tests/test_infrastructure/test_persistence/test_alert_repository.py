"""C1: alert item <-> AlertRecord, tolerant of alerts written before the
metrics snapshot existed."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.domain.alerts.exceptions import AlertPayloadTooLargeError
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    MAX_ALERT_PAYLOAD_BYTES,
    DynamoAlertRepository,
    _from_item,
    _to_item,
    created_day_for,
    snapshot_from_item,
    snapshot_to_item,
)

CREATED = datetime(2026, 10, 2, 3, 30, tzinfo=UTC)  # Oct 1 22:30 Bogota


def _alert(**overrides) -> AlertRecord:
    values = dict(
        id=uuid4(),
        event_id="evt-1",
        event_type="payment",
        input={"amount": {"baseValue": 10.5}},
        status=AlertStatus.CLOSED,
        created_at=CREATED,
        updated_at=CREATED,
    )
    values.update(overrides)
    return AlertRecord(**values)


def test_pre_snapshot_alert_item_hydrates_without_metrics() -> None:
    item = _to_item(_alert(), "America/Bogota")
    item.pop("created_day")
    assert "metrics" not in item

    alert = _from_item(item)
    assert alert.metrics is None


def test_item_carries_bogota_created_day_for_the_index() -> None:
    assert _to_item(_alert(), "America/Bogota")["created_day"] == "2026-10-01"
    assert created_day_for(CREATED, "UTC") == "2026-10-02"


def test_snapshot_round_trips_through_the_item() -> None:
    snapshot = AlertMetricsSnapshot(
        origin="production",
        segment="tarjetas",
        channel="POS",
        subchannel="CHIP",
        amount=1234.56,
        amount_tier="low",
        schema_version=2,
        configuration_id="default",
        resolution_method=AlertResolutionMethod.ANALYST,
        mark=Mark.FRAUD,
        fraud_label=Mark.NO_FRAUD,
        marked_at=CREATED,
        fraud_reviewed_at=CREATED,
        fraud_review_count=2,
        resolution_time_seconds=95.5,
        status=AlertStatus.CLOSED,
        snapshot_version=5,
    )
    item = _to_item(_alert(metrics=snapshot), "America/Bogota")
    assert item["metrics"]["amount"] == Decimal("1234.56")

    assert _from_item(item).metrics == snapshot


def test_partial_or_unknown_snapshot_fields_fall_back_to_defaults() -> None:
    restored = snapshot_from_item(
        {"snapshot_version": Decimal(3), "mark": "bogus", "status": "CLOSED"}
    )
    assert restored == AlertMetricsSnapshot(
        status=AlertStatus.CLOSED, snapshot_version=3
    )
    assert snapshot_from_item(None) is None
    assert "segment" not in snapshot_to_item(AlertMetricsSnapshot())


class RecordingTable:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def put_item(self, *, Item: dict) -> None:
        self.items.append(Item)


def test_create_rejects_payload_over_dynamodb_budget_before_writing() -> None:
    repository = DynamoAlertRepository.__new__(DynamoAlertRepository)
    repository._table = RecordingTable()
    repository._timezone_name = "America/Bogota"
    payload = {"data": "x" * MAX_ALERT_PAYLOAD_BYTES}

    with pytest.raises(AlertPayloadTooLargeError):
        repository.create(_alert(), raw_payload=payload)

    assert repository._table.items == []


def test_create_accepts_payload_within_dynamodb_budget() -> None:
    repository = DynamoAlertRepository.__new__(DynamoAlertRepository)
    repository._table = RecordingTable()
    repository._timezone_name = "America/Bogota"
    payload = {"eventId": "evt-1"}

    repository.create(_alert(), raw_payload=payload)

    assert len(repository._table.items) == 1

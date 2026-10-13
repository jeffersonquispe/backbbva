"""Docker-only: the fraud_label_reviews table (append-only, chronological
per alert) and the alert history's newest-first slices of CreatedDayIdx.
Run with `make test-integration-metrics`."""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip("Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True)

from botocore.exceptions import ClientError

from src.application.ports.alert_port import AlertRecord, AlertStatus, Mark
from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)
from src.infrastructure.persistence.database.dynamodb.manager import (
    create_table,
    ensure_global_secondary_indexes,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_label_review_repository import (
    DynamoFraudLabelReviewRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERTS_TABLE,
    FRAUD_LABEL_REVIEWS_TABLE,
)

pytestmark = pytest.mark.docker_integration

TZ = "America/Bogota"


@pytest.fixture(scope="module")
def tables():
    create_table(ALERTS_TABLE)
    ensure_global_secondary_indexes(ALERTS_TABLE)
    create_table(FRAUD_LABEL_REVIEWS_TABLE)


def test_reviews_are_appended_and_listed_oldest_first(tables) -> None:
    repo = DynamoFraudLabelReviewRepository()
    alert_id = uuid.uuid4()
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    second = FraudLabelReview(
        uuid.uuid4(), alert_id, Mark.NO_FRAUD, Mark.FRAUD, "b@x", t0 + timedelta(hours=1),
        FraudLabelReviewChannel.CSV, "chargeback",
    )
    first = FraudLabelReview(
        uuid.uuid4(), alert_id, Mark.FRAUD, Mark.NO_FRAUD, "a@x", t0, FraudLabelReviewChannel.UI, "",
    )
    repo.create(second)
    repo.create(first)

    assert repo.list_by_alert(alert_id) == [first, second]
    with pytest.raises(ClientError):  # never overwritten
        repo.create(first)


def test_page_by_created_day_is_newest_first_and_resumes_before_a_timestamp(tables) -> None:
    repo = DynamoAlertRepository(TZ)
    day = date(2031, 1, 15)  # a day no other test writes to
    base = datetime(2031, 1, 15, 12, 0, tzinfo=timezone.utc)  # 07:00 Bogota
    alerts = [
        AlertRecord(
            id=uuid.uuid4(), event_id=f"evt-{i}", event_type="payment", input={},
            status=AlertStatus.CLOSED, created_at=base + timedelta(minutes=i),
            updated_at=base + timedelta(minutes=i),
        )
        for i in range(5)
    ]
    try:
        for alert in alerts:
            repo.create(alert)
        newest_first = [a.id for a in reversed(alerts)]

        first = repo.page_by_created_day(day, before=None, limit=2)
        assert [a.id for a in first] == newest_first[:2]
        rest = repo.page_by_created_day(day, before=first[-1].created_at, limit=10)
        assert [a.id for a in rest] == newest_first[2:]
    finally:
        for alert in alerts:
            repo.delete(alert.id)

from datetime import UTC, datetime
from uuid import uuid4

from src.domain.alerts.entities import AlertRecord, AlertStatus


def test_alert_keeps_versioned_schema_and_dynamic_fields() -> None:
    now = datetime.now(UTC)
    alert = AlertRecord(
        id=uuid4(),
        event_id="evt-1",
        event_type="transfer",
        status=AlertStatus.RECEIVED,
        created_at=now,
        updated_at=now,
        schema_version=3,
        input={"new_field_added_in_schema_v3": {"nested": True}},
        labels={"review_outcome": "pending"},
    )

    assert alert.schema_version == 3
    assert alert.input["new_field_added_in_schema_v3"] == {"nested": True}
    assert alert.labels == {"review_outcome": "pending"}


def test_alert_collections_are_independent_by_default() -> None:
    now = datetime.now(UTC)
    first = AlertRecord(uuid4(), "evt-1", "transfer", AlertStatus.RECEIVED, now, now)
    second = AlertRecord(uuid4(), "evt-2", "transfer", AlertStatus.RECEIVED, now, now)

    first.input["customer_field"] = "value"

    assert second.input == {}

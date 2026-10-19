from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertStatus,
    Mark,
)
from src.domain.datasets.mature_sampling import (
    MatureSampleSpec,
    deterministic_partition,
    deterministic_sample,
    is_mature,
)


def _alert(label: Mark, created_day: int) -> AlertRecord:
    created = datetime(2026, 1, created_day, tzinfo=UTC)
    return AlertRecord(
        id=uuid4(),
        event_id=str(uuid4()),
        event_type="test",
        status=AlertStatus.CLOSED,
        created_at=created,
        updated_at=created,
        metrics=AlertMetricsSnapshot(fraud_label=label),
    )


def test_maturity_requires_final_label_and_elapsed_window() -> None:
    mature = _alert(Mark.FRAUD, 1)
    pending = _alert(Mark.PENDING, 1)
    recent = _alert(Mark.NO_FRAUD, 8)

    assert is_mature(mature, as_of=date(2026, 1, 10), maturing_days=4)
    assert not is_mature(pending, as_of=date(2026, 1, 10), maturing_days=4)
    assert not is_mature(recent, as_of=date(2026, 1, 10), maturing_days=4)


def test_schema_mapping_drives_target_and_marking_date_maturity() -> None:
    alert = _alert(Mark.PENDING, 1)
    alert.labels = {"resultado_operativo": "No fraude"}
    alert.input = {"fecha_decision": "2026-01-05T09:00:00Z"}
    mapping = {"no fraude": "no_fraud", "Fraude": "fraud"}

    assert is_mature(
        alert,
        as_of=date(2026, 1, 10),
        maturing_days=4,
        target_field="resultado_operativo",
        marking_date_field="fecha_decision",
        label_value_mapping=mapping,
    )
    assert not is_mature(
        alert,
        as_of=date(2026, 1, 10),
        maturing_days=6,
        target_field="resultado_operativo",
        marking_date_field="fecha_decision",
        label_value_mapping=mapping,
    )
    assert not is_mature(
        alert,
        as_of=date(2026, 1, 10),
        maturing_days=4,
        target_field="resultado_operativo",
        marking_date_field="fecha_decision",
        label_value_mapping={"Fraude": "fraud"},
    )


def test_same_specification_and_seed_return_same_sample_and_partitions() -> None:
    alerts = [_alert(Mark.FRAUD if index % 4 == 0 else Mark.NO_FRAUD, 1) for index in range(20)]
    spec = MatureSampleSpec(
        as_of=date(2026, 1, 10),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 5),
        maturing_days=4,
        sample_size=8,
        seed=44,
    )

    first = deterministic_sample(alerts, spec)
    second = deterministic_sample(alerts, spec)

    assert [item.id for item in first] == [item.id for item in second]
    assert [deterministic_partition(str(item.id), spec) for item in first] == [
        deterministic_partition(str(item.id), spec) for item in second
    ]
    assert len(first) == 8


def test_invalid_partition_proportions_are_rejected() -> None:
    spec = MatureSampleSpec(
        as_of=date(2026, 1, 10),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 5),
        maturing_days=4,
        sample_size=8,
        seed=44,
        test_proportion=0.3,
    )
    with pytest.raises(ValueError, match="proporciones"):
        spec.validate()

from datetime import UTC, date, datetime
from uuid import UUID

from hypothesis import given
from hypothesis import strategies as st

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
)


def _alert(index: int, label: Mark) -> AlertRecord:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return AlertRecord(
        id=UUID(int=index + 1),
        event_id=f"event-{index}",
        event_type="payment",
        status=AlertStatus.CLOSED,
        created_at=created_at,
        updated_at=created_at,
        metrics=AlertMetricsSnapshot(fraud_label=label),
    )


@given(
    labels=st.lists(
        st.sampled_from([Mark.FRAUD, Mark.NO_FRAUD, Mark.PENDING]),
        min_size=0,
        max_size=50,
    ),
    sample_size=st.integers(min_value=1, max_value=50),
    seed=st.integers(),
)
def test_mature_sampling_is_bounded_repeatable_and_excludes_pending(
    labels: list[Mark], sample_size: int, seed: int
) -> None:
    alerts = [_alert(index, label) for index, label in enumerate(labels)]
    spec = MatureSampleSpec(
        as_of=date(2026, 1, 20),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 20),
        maturing_days=5,
        sample_size=sample_size,
        seed=seed,
    )

    first = deterministic_sample(alerts, spec)
    second = deterministic_sample(alerts, spec)
    selected_ids = [alert.id for alert in first]
    eligible_ids = {
        alert.id for alert in alerts if alert.metrics.fraud_label is not Mark.PENDING
    }

    assert first == second
    assert len(first) <= sample_size
    assert len(selected_ids) == len(set(selected_ids))
    assert set(selected_ids) <= eligible_ids
    assert all(alert.metrics.fraud_label is not Mark.PENDING for alert in first)


@given(seed=st.integers(), alert_id=st.text(min_size=1, max_size=80))
def test_partition_is_stable_and_uses_a_known_bucket(seed: int, alert_id: str) -> None:
    spec = MatureSampleSpec(
        as_of=date(2026, 1, 20),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 20),
        maturing_days=5,
        sample_size=10,
        seed=seed,
    )

    result = deterministic_partition(alert_id, spec)

    assert result == deterministic_partition(alert_id, spec)
    assert result in {"training", "validation", "test", "final"}

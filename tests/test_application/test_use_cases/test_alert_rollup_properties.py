from dataclasses import replace
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from src.application.ports.metrics_rollup_port import RollupLevel
from src.application.use_cases.metrics.alert_rollup_contribution import (
    contribution,
    diff,
    live_periods,
)
from src.domain.alerts.entities import AlertMetricsSnapshot, Mark


def _snapshot(
    amount: float | None,
    resolution_seconds: float | None,
    mark: Mark,
    fraud_label: Mark,
) -> AlertMetricsSnapshot:
    return AlertMetricsSnapshot(
        amount=amount,
        resolution_time_seconds=resolution_seconds,
        mark=mark,
        fraud_label=fraud_label,
        marked_at=datetime(2026, 1, 1, tzinfo=UTC),
        fraud_reviewed_at=datetime(2026, 1, 2, tzinfo=UTC)
        if fraud_label is not Mark.PENDING
        else None,
        fraud_review_count=1,
    )


MEASURE = st.one_of(
    st.none(),
    st.floats(min_value=-1e12, max_value=1e12, allow_nan=False, allow_infinity=False),
)
SECONDS = st.one_of(
    st.none(),
    st.floats(min_value=-100_000, max_value=10_000_000, allow_nan=False, allow_infinity=False),
)


@given(age_days=st.integers(min_value=0, max_value=1_000))
def test_daily_rollup_expires_at_the_configured_retention_boundary(age_days: int) -> None:
    today = datetime(2026, 10, 25, tzinfo=UTC).date()
    periods = live_periods(today - timedelta(days=age_days), today)
    levels = [level for level, _ in periods]

    assert (RollupLevel.DAY in levels) is (age_days < 90)
    assert RollupLevel.MONTH in levels
    assert RollupLevel.YEAR in levels


@given(
    old_amount=MEASURE,
    new_amount=MEASURE,
    old_seconds=SECONDS,
    new_seconds=SECONDS,
    old_mark=st.sampled_from(list(Mark)),
    new_mark=st.sampled_from(list(Mark)),
    old_label=st.sampled_from(list(Mark)),
    new_label=st.sampled_from(list(Mark)),
)
def test_rollup_delta_equals_new_contribution_minus_old(
    old_amount: float | None,
    new_amount: float | None,
    old_seconds: float | None,
    new_seconds: float | None,
    old_mark: Mark,
    new_mark: Mark,
    old_label: Mark,
    new_label: Mark,
) -> None:
    created = datetime(2026, 1, 1, 12, tzinfo=UTC)
    now = created + timedelta(days=1)
    old = _snapshot(old_amount, old_seconds, old_mark, old_label)
    new = _snapshot(new_amount, new_seconds, new_mark, new_label)
    old_measures = contribution(old, created, UTC).measures
    new_measures = contribution(new, created, UTC).measures

    deltas = diff(old, new, created, now, UTC)

    for level in {delta.key.level for delta in deltas}:
        level_deltas = [delta for delta in deltas if delta.key.level == level]
        actual: dict[str, float] = {}
        for delta in level_deltas:
            for measure, value in delta.measures.items():
                actual[measure] = actual.get(measure, 0) + value
        expected = {
            key: new_measures.get(key, 0) - old_measures.get(key, 0)
            for key in old_measures.keys() | new_measures.keys()
        }
        expected = {key: value for key, value in expected.items() if value != 0}
        actual = {key: value for key, value in actual.items() if value != 0}
        assert actual == expected


@given(amount=MEASURE, seconds=SECONDS)
def test_unchanged_snapshot_never_emits_rollup_deltas(
    amount: float | None, seconds: float | None
) -> None:
    snapshot = _snapshot(amount, seconds, Mark.FRAUD, Mark.FRAUD)
    created = datetime(2026, 1, 1, 12, tzinfo=UTC)

    assert diff(snapshot, replace(snapshot), created, created, UTC) == []

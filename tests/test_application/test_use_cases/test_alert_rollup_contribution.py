"""R2 contribution/diff + Q6 Bogota bucket edges."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from src.application.ports.metrics_rollup_port import (
    ALERT_DIMENSIONS,
    MetricsDataType,
    RollupLevel,
)
from src.application.use_cases.metrics.alert_rollup_contribution import (
    contribution,
    diff,
    live_periods,
)
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)

TZ = "America/Bogota"  # UTC-5, no DST
NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


def _snapshot(**overrides) -> AlertMetricsSnapshot:
    base = AlertMetricsSnapshot(
        origin="production",
        segment="canales_digitales",
        channel="WEB",
        subchannel="PSE",
        amount=1500.0,
        amount_tier="low",
        schema_version=1,
        configuration_id="default",
        status=AlertStatus.CLOSED,
        snapshot_version=1,
    )
    return replace(base, **overrides)


def _periods(deltas):
    return sorted((d.key.level.value, d.key.period) for d in deltas)


# --- Q6: timezone bucket edges -------------------------------------------------


def test_2330_bogota_is_next_day_in_utc_but_buckets_on_the_bogota_day() -> None:
    # 2026-10-02 04:30 UTC == 2026-10-01 23:30 Bogota
    created = datetime(2026, 10, 2, 4, 30, tzinfo=UTC)
    part = contribution(_snapshot(), created, TZ)
    assert part.local_date == date(2026, 10, 1)
    assert part.hour == 23


def test_midnight_bogota_opens_the_new_day_at_hour_zero() -> None:
    created = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)  # 00:00 Bogota
    part = contribution(_snapshot(), created, TZ)
    assert (part.local_date, part.hour) == (date(2026, 10, 2), 0)


def test_month_edge_last_utc_hours_stay_in_previous_bogota_month() -> None:
    created = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)  # Oct 31 21:00 Bogota
    deltas = diff(None, _snapshot(), created, NOW + timedelta(days=40), TZ)
    assert _periods(deltas) == [
        ("day", "2026-10-31"),
        ("month", "2026-10"),
        ("year", "2026"),
    ]


def test_year_edge_new_year_utc_is_still_december_31_in_bogota() -> None:
    created = datetime(2027, 1, 1, 3, 0, tzinfo=UTC)  # Dec 31 22:00 Bogota
    now = datetime(2027, 1, 2, tzinfo=UTC)
    deltas = diff(None, _snapshot(), created, now, TZ)
    assert _periods(deltas) == [
        ("day", "2026-12-31"),
        ("month", "2026-12"),
        ("year", "2026"),
    ]
    assert {d.hour for d in deltas} == {22}


# --- live levels -----------------------------------------------------------------


def test_alert_120_days_old_only_touches_month_and_year() -> None:
    created = NOW - timedelta(days=120)
    deltas = diff(None, _snapshot(), created, NOW, TZ)
    assert [d.key.level for d in deltas] == [RollupLevel.MONTH, RollupLevel.YEAR]


def test_day_level_lives_for_ages_0_to_89() -> None:
    today = date(2026, 10, 1)
    assert live_periods(today - timedelta(days=89), today)[0][0] == RollupLevel.DAY
    assert live_periods(today - timedelta(days=90), today)[0][0] == RollupLevel.MONTH


# --- contribution / diff -----------------------------------------------------------


def test_new_alert_adds_one_count_and_amount_on_every_live_level() -> None:
    created = datetime(2026, 10, 1, 14, 10, tzinfo=UTC)  # 09:10 Bogota
    deltas = diff(None, _snapshot(), created, NOW, TZ)
    assert len(deltas) == 3
    for delta in deltas:
        assert delta.key.data_type == MetricsDataType.ALERT
        assert delta.hour == 9
        assert delta.measures == {"count": 1, "amount_sum": 1500.0, "amount_count": 1}
        assert [name for name, _ in delta.key.dimensions] == list(ALERT_DIMENSIONS)
    assert deltas[0].key.dimension("mark") == "pending"
    assert deltas[0].key.dimension("resolution_method") == "unknown"


def test_unchanged_snapshot_yields_no_delta_even_if_version_differs() -> None:
    created = NOW - timedelta(hours=2)
    old = _snapshot()
    assert diff(old, replace(old, snapshot_version=7), created, NOW, TZ) == []


def test_dimension_change_moves_the_alert_between_rows() -> None:
    created = NOW - timedelta(hours=2)
    old = _snapshot(segment=None)
    new = _snapshot(segment="tarjetas")
    deltas = diff(old, new, created, NOW, TZ)
    day = [d for d in deltas if d.key.level == RollupLevel.DAY]
    by_segment = {d.key.dimension("segment"): d.measures for d in day}
    assert by_segment["unknown"] == {
        "count": -1,
        "amount_sum": -1500.0,
        "amount_count": -1,
    }
    assert by_segment["tarjetas"] == {
        "count": 1,
        "amount_sum": 1500.0,
        "amount_count": 1,
    }


def test_measure_only_change_stays_on_the_same_row_and_nets_out() -> None:
    created = NOW - timedelta(hours=2)
    old = _snapshot(fraud_label=Mark.FRAUD, mark=Mark.FRAUD)
    marked = created + timedelta(minutes=3)
    new = replace(old, fraud_label=Mark.FRAUD, mark=Mark.FRAUD)
    # same dims, add a resolution time -> one row per level, only rt measures
    new = replace(new, resolution_time_seconds=180.0, marked_at=marked)
    deltas = diff(old, new, created, NOW, TZ)
    assert len(deltas) == 3
    assert deltas[0].measures == {"rt_count": 1, "rt_sum_seconds": 180.0, "rt_1_5m": 1}


def test_decision_snapshot_measures_resolution_histogram() -> None:
    created = NOW - timedelta(hours=1)
    snapshot = _snapshot(
        mark=Mark.FRAUD,
        fraud_label=Mark.FRAUD,
        resolution_method=AlertResolutionMethod.ARIA,
        marked_at=created + timedelta(minutes=20),
        resolution_time_seconds=1200.0,
    )
    part = contribution(snapshot, created, TZ)
    assert part.measures["rt_15_30m"] == 1
    assert dict(part.dimensions)["resolution_method"] == "aria"


def test_fraud_review_measures_change_confirmation_and_maturation() -> None:
    created = NOW - timedelta(days=10)
    marked = created + timedelta(minutes=2)
    decided = _snapshot(
        mark=Mark.FRAUD,
        fraud_label=Mark.FRAUD,
        marked_at=marked,
        resolution_time_seconds=120.0,
    )
    corrected = replace(
        decided,
        fraud_label=Mark.NO_FRAUD,
        fraud_reviewed_at=marked + timedelta(days=2),
        fraud_review_count=1,
    )
    measures = contribution(corrected, created, TZ).measures
    assert measures["reviewed_count"] == 1
    assert measures["reviewed_changed_count"] == 1
    assert "reviewed_confirmed_count" not in measures
    assert measures["mat_1_4d"] == 1

    confirmed = replace(corrected, fraud_label=Mark.FRAUD)
    assert (
        contribution(confirmed, created, TZ).measures["reviewed_confirmed_count"] == 1
    )

    # The correction moves the alert from the (fraud, fraud) row to the
    # (fraud, no_fraud) row: that is the false positive.
    deltas = diff(decided, corrected, created, NOW, TZ)
    day = {
        d.key.dimension("fraud_label"): d
        for d in deltas
        if d.key.level == RollupLevel.DAY
    }
    assert day["fraud"].measures["count"] == -1
    assert day["no_fraud"].measures["count"] == 1

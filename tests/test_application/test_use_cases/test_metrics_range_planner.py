"""A1 range planner + Q6 timezone bucketing tests (pure function, no fakes needed)."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.application.use_cases.metrics.range_planner import (
    ALL_HOURS,
    Maturation,
    RollupLevel,
    plan,
)

BOG = ZoneInfo("America/Bogota")
# Local today = 2026-10-01 -> 90-day window starts 2026-07-04 (age 89).
NOW = datetime(2026, 10, 1, 14, 37, tzinfo=BOG)


def bog(*args: int) -> datetime:
    return datetime(*args, tzinfo=BOG)


def summary(reads):
    return [(r.level, r.period, r.hours, r.partial) for r in reads]


def test_last_24h_is_yesterday_from_next_hour_plus_today_up_to_now():
    reads = plan(NOW - timedelta(hours=24), NOW, NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.DAY, "2026-09-30", tuple(range(15, 24)), False),
        (RollupLevel.DAY, "2026-10-01", tuple(range(0, 15)), False),
    ]
    assert sum(len(r.hours) for r in reads) == 24
    assert all(r.maturation is Maturation.MATURING for r in reads)


def test_range_crossing_midnight_splits_hours_between_days():
    reads = plan(bog(2026, 9, 20, 22), bog(2026, 9, 21, 2), NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.DAY, "2026-09-20", (22, 23), False),
        (RollupLevel.DAY, "2026-09-21", (0, 1), False),
    ]


def test_2330_bogota_belongs_to_bogota_date_not_utc_date():
    # 2026-09-20 23:30 Bogota == 2026-09-21 04:30 UTC.
    start = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    reads = plan(start, start + timedelta(hours=1), NOW, BOG)

    assert summary(reads) == [(RollupLevel.DAY, "2026-09-20", (23,), False)]


def test_utc_calendar_day_maps_to_two_bogota_days():
    reads = plan(
        datetime(2026, 9, 21, tzinfo=UTC),
        datetime(2026, 9, 22, tzinfo=UTC),
        NOW,
        BOG,
    )

    assert summary(reads) == [
        (RollupLevel.DAY, "2026-09-20", tuple(range(19, 24)), False),
        (RollupLevel.DAY, "2026-09-21", tuple(range(0, 19)), False),
    ]


def test_tz_name_string_is_accepted():
    a = plan(bog(2026, 9, 20), bog(2026, 9, 21), NOW, BOG)
    b = plan(bog(2026, 9, 20), bog(2026, 9, 21), NOW, "America/Bogota")
    assert a == b


def test_month_end_inside_window_uses_days():
    reads = plan(bog(2026, 8, 31, 20), bog(2026, 9, 1, 4), NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.DAY, "2026-08-31", (20, 21, 22, 23), False),
        (RollupLevel.DAY, "2026-09-01", (0, 1, 2, 3), False),
    ]


def test_full_week_inside_window_reads_full_days():
    reads = plan(bog(2026, 9, 1), bog(2026, 9, 8), NOW, BOG)

    assert [r.period for r in reads] == [f"2026-09-0{d}" for d in range(1, 8)]
    assert all(r.level is RollupLevel.DAY and r.hours == ALL_HOURS for r in reads)


def test_year_end_inside_window_uses_days():
    now = bog(2027, 1, 2, 12)
    reads = plan(bog(2026, 12, 31, 22), bog(2027, 1, 1, 2), now, BOG)

    assert summary(reads) == [
        (RollupLevel.DAY, "2026-12-31", (22, 23), False),
        (RollupLevel.DAY, "2027-01-01", (0, 1), False),
    ]


def test_year_end_outside_window_uses_partial_months():
    reads = plan(bog(2025, 12, 15), bog(2026, 1, 10), NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.MONTH, "2025-12", ALL_HOURS, True),
        (RollupLevel.MONTH, "2026-01", ALL_HOURS, True),
    ]
    assert reads[0].period_start == date(2025, 12, 1)
    assert reads[0].period_end == date(2025, 12, 31)


def test_day_row_exists_at_age_89_but_not_at_age_90():
    youngest_month_day = plan(bog(2026, 7, 4), bog(2026, 7, 5), NOW, BOG)
    assert summary(youngest_month_day) == [
        (RollupLevel.DAY, "2026-07-04", ALL_HOURS, False)
    ]

    expired_day = plan(bog(2026, 7, 3), bog(2026, 7, 4), NOW, BOG)
    assert summary(expired_day) == [(RollupLevel.MONTH, "2026-07", ALL_HOURS, True)]


def test_boundary_month_is_read_once_as_month_never_mixed_with_its_days():
    # Jul 1-3 are outside the window, Jul 4-9 inside: same month -> one row.
    reads = plan(bog(2026, 7, 1), bog(2026, 7, 10), NOW, BOG)

    assert summary(reads) == [(RollupLevel.MONTH, "2026-07", ALL_HOURS, True)]


def test_mix_at_boundary_full_months_then_days():
    reads = plan(bog(2026, 6, 1), bog(2026, 8, 3), NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.MONTH, "2026-06", ALL_HOURS, False),
        # July straddles the boundary but is fully covered -> exact month row.
        (RollupLevel.MONTH, "2026-07", ALL_HOURS, False),
        (RollupLevel.DAY, "2026-08-01", ALL_HOURS, False),
        (RollupLevel.DAY, "2026-08-02", ALL_HOURS, False),
    ]


def test_month_outside_window_with_partial_hours_is_flagged_partial():
    reads = plan(bog(2026, 5, 1, 6), bog(2026, 6, 1), NOW, BOG)

    assert summary(reads) == [(RollupLevel.MONTH, "2026-05", ALL_HOURS, True)]


def test_full_years_outside_window_collapse_to_year_rows():
    reads = plan(bog(2024, 1, 1), bog(2026, 3, 1), NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.YEAR, "2024", ALL_HOURS, False),
        (RollupLevel.YEAR, "2025", ALL_HOURS, False),
        (RollupLevel.MONTH, "2026-01", ALL_HOURS, False),
        (RollupLevel.MONTH, "2026-02", ALL_HOURS, False),
    ]


def test_partial_year_is_read_as_months():
    reads = plan(bog(2024, 1, 1), bog(2024, 12, 31), NOW, BOG)

    assert [r.level for r in reads] == [RollupLevel.MONTH] * 12
    assert [r.partial for r in reads] == [False] * 11 + [True]


def test_year_not_collapsed_when_it_reaches_into_the_window():
    now = bog(2027, 2, 1, 12)  # window starts 2026-11-04
    reads = plan(bog(2026, 1, 1), bog(2027, 1, 1), now, BOG)

    assert all(r.level is not RollupLevel.YEAR for r in reads)
    months = [r.period for r in reads if r.level is RollupLevel.MONTH]
    assert months[0] == "2026-01"
    assert months[-1] == "2026-11"  # boundary month, fully covered
    days = [r.period for r in reads if r.level is RollupLevel.DAY]
    assert days[0] == "2026-12-01" and days[-1] == "2026-12-31"


def test_leap_day_inside_window():
    now = bog(2028, 3, 15, 12)
    reads = plan(bog(2028, 2, 28), bog(2028, 3, 1), now, BOG)

    assert [r.period for r in reads] == ["2028-02-28", "2028-02-29"]


def test_leap_february_outside_window_needs_feb_29_to_be_exact():
    full = plan(bog(2024, 2, 1), bog(2024, 3, 1), NOW, BOG)
    assert summary(full) == [(RollupLevel.MONTH, "2024-02", ALL_HOURS, False)]
    assert full[0].period_end == date(2024, 2, 29)

    missing_leap_day = plan(bog(2024, 2, 1), bog(2024, 2, 29), NOW, BOG)
    assert missing_leap_day[0].partial is True


def test_maturation_thresholds():
    reads = plan(bog(2026, 9, 26), bog(2026, 9, 29), NOW, BOG)
    by_period = {r.period: r.maturation for r in reads}
    assert by_period == {
        "2026-09-26": Maturation.MAY_VARY,  # age 5
        "2026-09-27": Maturation.MAY_VARY,  # age 4
        "2026-09-28": Maturation.MATURING,  # age 3
    }

    months = plan(bog(2026, 3, 1), bog(2026, 5, 1), NOW, BOG)
    # Cut-off is today - 6 months = 2026-04-01; youngest date of the row decides.
    assert {r.period: r.maturation for r in months} == {
        "2026-03": Maturation.STABLE,
        "2026-04": Maturation.MAY_VARY,
    }


def test_to_in_future_is_clamped_to_now():
    reads = plan(bog(2026, 10, 1), bog(2026, 10, 3), NOW, BOG)

    assert summary(reads) == [
        (RollupLevel.DAY, "2026-10-01", tuple(range(0, 15)), False)
    ]


def test_empty_and_sub_hour_ranges_yield_nothing():
    assert plan(bog(2026, 9, 1), bog(2026, 9, 1), NOW, BOG) == []
    assert plan(bog(2026, 9, 1, 10, 10), bog(2026, 9, 1, 10, 50), NOW, BOG) == []
    assert plan(bog(2026, 10, 2), bog(2026, 10, 3), NOW, BOG) == []


def test_from_after_to_raises():
    with pytest.raises(ValueError):
        plan(bog(2026, 9, 2), bog(2026, 9, 1), NOW, BOG)


def test_naive_datetimes_raise():
    with pytest.raises(ValueError):
        plan(datetime(2026, 9, 1), bog(2026, 9, 2), NOW, BOG)

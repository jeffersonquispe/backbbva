"""What one alert's metrics snapshot adds to the rollups (R2), and the delta
between two snapshots of the same alert. Pure functions: no I/O, the
timezone is a parameter (callers pass the operations timezone).

Buckets are keyed by the alert's arrival (created_at) in local time, never
by when the data arrived: a fraud_label correction months later lands on
the alert's own day/month/year rows. A delta touches every level still
alive for that date - day while the date is < 90 days old, month and year
always."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from src.application.ports.alert_port import AlertMetricsSnapshot, Mark
from src.application.ports.metrics_rollup_port import (
    ALERT_DIMENSIONS,
    DAY_LEVEL_RETENTION_DAYS,
    UNKNOWN_DIMENSION,
    MetricsDataType,
    RollupDelta,
    RollupKey,
    RollupLevel,
)

# --- measure names (all additive) -------------------------------------------

COUNT = "count"
AMOUNT_SUM = "amount_sum"
AMOUNT_COUNT = "amount_count"
RESOLUTION_TIME_COUNT = "rt_count"
RESOLUTION_TIME_SUM_SECONDS = "rt_sum_seconds"
REVIEWED_COUNT = "reviewed_count"
REVIEWED_CHANGED_COUNT = "reviewed_changed_count"
REVIEWED_CONFIRMED_COUNT = "reviewed_confirmed_count"
REVIEW_EVENTS = "review_events"

# (measure, upper bound exclusive in seconds; None = unbounded). Gives an
# exact "% resolved < 5 min" (rt_lt_1m + rt_1_5m) and an approximate p95.
RESOLUTION_TIME_BUCKETS: tuple[tuple[str, float | None], ...] = (
    ("rt_lt_1m", 60),
    ("rt_1_5m", 5 * 60),
    ("rt_5_15m", 15 * 60),
    ("rt_15_30m", 30 * 60),
    ("rt_gt_30m", None),
)

_DAY = 24 * 3600
# fraud_reviewed_at - marked_at: < 1 d, 1-4 d, 4-30 d, 1-6 months, > 6 months.
MATURATION_BUCKETS: tuple[tuple[str, float | None], ...] = (
    ("mat_lt_1d", _DAY),
    ("mat_1_4d", 4 * _DAY),
    ("mat_4_30d", 30 * _DAY),
    ("mat_1_6mo", 183 * _DAY),
    ("mat_gt_6mo", None),
)


@dataclass(frozen=True)
class AlertContribution:
    local_date: date
    hour: int
    dimensions: tuple[tuple[str, str], ...]
    measures: dict[str, float] = field(default_factory=dict)


def _zone(tz: tzinfo | str) -> tzinfo:
    return ZoneInfo(tz) if isinstance(tz, str) else tz


def _dim(value: object) -> str:
    if value is None or value == "":
        return UNKNOWN_DIMENSION
    return str(getattr(value, "value", value))


def _bucket(buckets: tuple[tuple[str, float | None], ...], seconds: float) -> str:
    for name, upper in buckets:
        if upper is None or seconds < upper:
            return name
    return buckets[-1][0]


def alert_dimensions(snapshot: AlertMetricsSnapshot) -> tuple[tuple[str, str], ...]:
    return tuple((name, _dim(getattr(snapshot, name))) for name in ALERT_DIMENSIONS)


def alert_measures(snapshot: AlertMetricsSnapshot) -> dict[str, float]:
    measures: dict[str, float] = {COUNT: 1}
    if snapshot.amount is not None:
        measures[AMOUNT_SUM] = snapshot.amount
        measures[AMOUNT_COUNT] = 1
    if snapshot.resolution_time_seconds is not None:
        seconds = max(snapshot.resolution_time_seconds, 0.0)
        measures[RESOLUTION_TIME_COUNT] = 1
        measures[RESOLUTION_TIME_SUM_SECONDS] = seconds
        measures[_bucket(RESOLUTION_TIME_BUCKETS, seconds)] = 1
    if snapshot.fraud_reviewed_at is not None:
        measures[REVIEWED_COUNT] = 1
        measures[REVIEW_EVENTS] = snapshot.fraud_review_count
        # A review of a still-pending mark is neither a change nor a
        # confirmation of a decision.
        if snapshot.mark != Mark.PENDING:
            if snapshot.fraud_label != snapshot.mark:
                measures[REVIEWED_CHANGED_COUNT] = 1
            else:
                measures[REVIEWED_CONFIRMED_COUNT] = 1
        if snapshot.marked_at is not None:
            maturation = max(
                (snapshot.fraud_reviewed_at - snapshot.marked_at).total_seconds(), 0.0
            )
            measures[_bucket(MATURATION_BUCKETS, maturation)] = 1
    return measures


def contribution(
    snapshot: AlertMetricsSnapshot, created_at: datetime, tz: tzinfo | str
) -> AlertContribution:
    """(dimensions, hour of day, measures) this snapshot adds, bucketed by
    the alert's arrival in local time."""
    local = created_at.astimezone(_zone(tz))
    return AlertContribution(
        local_date=local.date(),
        hour=local.hour,
        dimensions=alert_dimensions(snapshot),
        measures=alert_measures(snapshot),
    )


def live_periods(local_date: date, today: date) -> list[tuple[RollupLevel, str]]:
    """The levels that still exist for this date: day only while it is
    younger than DAY_LEVEL_RETENTION_DAYS, month and year always."""
    periods: list[tuple[RollupLevel, str]] = []
    if (today - local_date) < timedelta(days=DAY_LEVEL_RETENTION_DAYS):
        periods.append((RollupLevel.DAY, local_date.isoformat()))
    periods.append((RollupLevel.MONTH, f"{local_date.year:04d}-{local_date.month:02d}"))
    periods.append((RollupLevel.YEAR, f"{local_date.year:04d}"))
    return periods


def diff(
    old: AlertMetricsSnapshot | None,
    new: AlertMetricsSnapshot | None,
    created_at: datetime,
    now: datetime,
    tz: tzinfo | str,
) -> list[RollupDelta]:
    """-old +new on every live level for the alert's date. Increments on
    the same row/hour are merged and zero increments dropped, so an
    unchanged snapshot yields []. snapshot_version is not a dimension or
    measure, so it never produces a delta by itself."""
    zone = _zone(tz)
    today = now.astimezone(zone).date()
    merged: dict[tuple[RollupKey, int], dict[str, float]] = {}
    for snapshot, sign in ((old, -1), (new, 1)):
        if snapshot is None:
            continue
        part = contribution(snapshot, created_at, zone)
        for level, period in live_periods(part.local_date, today):
            key = RollupKey(
                data_type=MetricsDataType.ALERT,
                level=level,
                period=period,
                dimensions=part.dimensions,
            )
            slot = merged.setdefault((key, part.hour), {})
            for measure, value in part.measures.items():
                slot[measure] = slot.get(measure, 0) + sign * value
    deltas: list[RollupDelta] = []
    for (key, hour), measures in merged.items():
        nonzero = {name: value for name, value in measures.items() if value != 0}
        if nonzero:
            deltas.append(RollupDelta(key=key, hour=hour, measures=nonzero))
    return deltas

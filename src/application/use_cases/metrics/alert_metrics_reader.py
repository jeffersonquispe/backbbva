"""Shared read side of the alert rollups for /metrics/overview and
/metrics/agent: plan the range (range_planner), read the planned rows with
the filters pushed down to the repository, and fold additive measures into
the response DTOs. Only sums of stored measures - never an average, rate
or distinct count (the client divides numerator by denominator)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.application.dtos.metrics_dtos import (
    DimensionBucket,
    FraudQualityStats,
    HistogramBucket,
    HourlyProfileSlot,
    MetricsPeriod,
    MetricsQueryInput,
    MetricsRange,
    MetricsTotals,
    MetricsWarning,
    ResolutionTimeStats,
)
from src.application.ports.metrics_rollup_port import (
    MetricsDataType,
    MetricsRollupRepository,
    RollupLevel,
    RollupRow,
)
from src.application.use_cases.metrics.alert_rollup_contribution import (
    AMOUNT_COUNT,
    AMOUNT_SUM,
    COUNT,
    MATURATION_BUCKETS,
    RESOLUTION_TIME_BUCKETS,
    RESOLUTION_TIME_COUNT,
    RESOLUTION_TIME_SUM_SECONDS,
    REVIEW_EVENTS,
    REVIEWED_CHANGED_COUNT,
    REVIEWED_CONFIRMED_COUNT,
    REVIEWED_COUNT,
)
from src.application.use_cases.metrics.metrics_filters import normalize_filters
from src.application.use_cases.metrics.range_planner import PlannedRead, plan
from src.domain.alerts.entities import (
    Mark,
)

DEFAULT_RANGE = timedelta(hours=24)
# rt buckets whose upper bound is <= 5 min: the exact "resolved < 5 min".
SLA_SECONDS = 5 * 60
SLA_BUCKETS = tuple(
    name
    for name, upper in RESOLUTION_TIME_BUCKETS
    if upper is not None and upper <= SLA_SECONDS
)


@dataclass(frozen=True)
class PlannedRow:
    """A rollup row read for a planned period, with the hour slots of that
    period that fall in the range."""

    read: PlannedRead
    row: RollupRow

    def total(self, measure: str) -> float:
        return self.row.total(measure, self.read.hours)

    def dimension(self, name: str) -> str:
        return self.row.key.dimension(name) or "unknown"


@dataclass
class AlertRollupRead:
    range: MetricsRange
    reads: list[PlannedRead]
    rows: list[PlannedRow]


def read_alert_rollups(
    repository: MetricsRollupRepository,
    input: MetricsQueryInput,
    now: datetime,
    timezone_name: str,
) -> AlertRollupRead:
    """Raises ValueError for a naive/inverted range or an unknown filter."""
    to = input.to or now
    from_ = input.from_ or (to - DEFAULT_RANGE)
    filters = normalize_filters(input.filters)
    reads = plan(from_, to, now, timezone_name)
    by_level: dict[str, dict[str, PlannedRead]] = {}
    for read in reads:
        by_level.setdefault(read.level.value, {})[read.period] = read
    rows: list[PlannedRow] = []
    for level, periods in by_level.items():
        for row in repository.query(
            MetricsDataType.ALERT, RollupLevel(level), list(periods), filters or None
        ):
            read = periods.get(row.key.period)
            if read is not None:
                rows.append(PlannedRow(read=read, row=row))
    versions = sorted(
        {r.dimension("schema_version") for r in rows if r.total(COUNT) != 0}
    )
    return AlertRollupRead(
        range=MetricsRange(
            from_=from_, to=to, timezone=timezone_name, schema_versions=versions
        ),
        reads=reads,
        rows=rows,
    )


# --- folding -----------------------------------------------------------------


def _int(value: float) -> int:
    return int(round(value))


def _sum(rows: Iterable[PlannedRow], measure: str) -> float:
    return sum(r.total(measure) for r in rows)


def _is(rows: Iterable[PlannedRow], mark: Mark, label: Mark) -> list[PlannedRow]:
    return [
        r
        for r in rows
        if r.dimension("mark") == mark.value
        and r.dimension("fraud_label") == label.value
    ]


def _decided(rows: Iterable[PlannedRow]) -> list[PlannedRow]:
    return [
        r
        for r in rows
        if r.dimension("mark") in (Mark.FRAUD.value, Mark.NO_FRAUD.value)
    ]


def count_where(rows: Iterable[PlannedRow], dimension: str, value: str) -> int:
    return _int(_sum((r for r in rows if r.dimension(dimension) == value), COUNT))


def _histogram(
    rows: list[PlannedRow], buckets: tuple[tuple[str, float | None], ...]
) -> list[HistogramBucket]:
    return [
        HistogramBucket(
            bucket=name, upper_bound_seconds=upper, count=_int(_sum(rows, name))
        )
        for name, upper in buckets
    ]


def totals(rows: list[PlannedRow]) -> MetricsTotals:
    return MetricsTotals(
        alerts=_int(_sum(rows, COUNT)),
        amount_sum=_sum(rows, AMOUNT_SUM),
        amount_count=_int(_sum(rows, AMOUNT_COUNT)),
    )


def fraud_quality(rows: list[PlannedRow]) -> FraudQualityStats:
    tp = _is(rows, Mark.FRAUD, Mark.FRAUD)
    tn = _is(rows, Mark.NO_FRAUD, Mark.NO_FRAUD)
    fp = _is(rows, Mark.FRAUD, Mark.NO_FRAUD)
    fn = _is(rows, Mark.NO_FRAUD, Mark.FRAUD)
    decided = _int(_sum(_decided(rows), COUNT))
    return FraudQualityStats(
        decided=decided,
        pending=_int(_sum(rows, COUNT)) - decided,
        true_positives=_int(_sum(tp, COUNT)),
        true_negatives=_int(_sum(tn, COUNT)),
        false_positives=_int(_sum(fp, COUNT)),
        undetected_fraud=_int(_sum(fn, COUNT)),
        true_positive_amount_sum=_sum(tp, AMOUNT_SUM),
        false_positive_amount_sum=_sum(fp, AMOUNT_SUM),
        undetected_fraud_amount_sum=_sum(fn, AMOUNT_SUM),
        reviewed=_int(_sum(rows, REVIEWED_COUNT)),
        reviewed_changed=_int(_sum(rows, REVIEWED_CHANGED_COUNT)),
        reviewed_confirmed=_int(_sum(rows, REVIEWED_CONFIRMED_COUNT)),
        review_events=_int(_sum(rows, REVIEW_EVENTS)),
        maturation_histogram=_histogram(rows, MATURATION_BUCKETS),
    )


def resolution_time(rows: list[PlannedRow]) -> ResolutionTimeStats:
    return ResolutionTimeStats(
        count=_int(_sum(rows, RESOLUTION_TIME_COUNT)),
        sum_seconds=_sum(rows, RESOLUTION_TIME_SUM_SECONDS),
        within_sla_count=_int(sum(_sum(rows, name) for name in SLA_BUCKETS)),
        histogram=_histogram(rows, RESOLUTION_TIME_BUCKETS),
    )


def dimension_buckets(
    rows: list[PlannedRow], dimension: str, order: list[str] | None = None
) -> list[DimensionBucket]:
    """One bucket per value present (alerts != 0), largest first - or, with
    `order`, exactly those values in that order (zeros included) followed by
    any other value present."""
    groups: dict[str, list[PlannedRow]] = {}
    for r in rows:
        groups.setdefault(r.dimension(dimension), []).append(r)

    def bucket(value: str) -> DimensionBucket:
        group = groups.get(value, [])
        quality = fraud_quality(group)
        return DimensionBucket(
            value=value,
            alerts=_int(_sum(group, COUNT)),
            amount_sum=_sum(group, AMOUNT_SUM),
            amount_count=_int(_sum(group, AMOUNT_COUNT)),
            decided=quality.decided,
            false_positives=quality.false_positives,
            undetected_fraud=quality.undetected_fraud,
        )

    present = [b for b in (bucket(v) for v in groups) if b.alerts != 0]
    if order is None:
        return sorted(present, key=lambda b: (-b.alerts, b.value))
    extra = sorted((b for b in present if b.value not in order), key=lambda b: b.value)
    return [bucket(v) for v in order] + extra


def dimension_distributions(
    rows: list[PlannedRow], dimensions: Iterable[str]
) -> dict[str, list[DimensionBucket]]:
    """Aggregate all dimension distributions in one row pass."""
    totals_by_dimension: dict[str, dict[str, dict[str, float]]] = {
        name: {} for name in dimensions
    }
    for row in rows:
        count = row.total(COUNT)
        amount_sum = row.total(AMOUNT_SUM)
        amount_count = row.total(AMOUNT_COUNT)
        decided = row.dimension("mark") in (Mark.FRAUD.value, Mark.NO_FRAUD.value)
        false_positive = (
            row.dimension("mark") == Mark.FRAUD.value
            and row.dimension("fraud_label") == Mark.NO_FRAUD.value
        )
        undetected = (
            row.dimension("mark") == Mark.NO_FRAUD.value
            and row.dimension("fraud_label") == Mark.FRAUD.value
        )
        for name in totals_by_dimension:
            value = row.dimension(name)
            bucket = totals_by_dimension[name].setdefault(
                value,
                {
                    "alerts": 0,
                    "amount_sum": 0,
                    "amount_count": 0,
                    "decided": 0,
                    "false_positives": 0,
                    "undetected_fraud": 0,
                },
            )
            bucket["alerts"] += count
            bucket["amount_sum"] += amount_sum
            bucket["amount_count"] += amount_count
            bucket["decided"] += count if decided else 0
            bucket["false_positives"] += count if false_positive else 0
            bucket["undetected_fraud"] += count if undetected else 0
    return {
        name: sorted(
            (
                DimensionBucket(
                    value=value,
                    alerts=_int(measures["alerts"]),
                    amount_sum=measures["amount_sum"],
                    amount_count=_int(measures["amount_count"]),
                    decided=_int(measures["decided"]),
                    false_positives=_int(measures["false_positives"]),
                    undetected_fraud=_int(measures["undetected_fraud"]),
                )
                for value, measures in groups.items()
                if measures["alerts"] != 0
            ),
            key=lambda bucket: (-bucket.alerts, bucket.value),
        )
        for name, groups in totals_by_dimension.items()
    }


def hourly_profile(rows: list[PlannedRow]) -> list[HourlyProfileSlot]:
    slots = [HourlyProfileSlot(hour=h) for h in range(24)]
    sums: list[dict[str, float]] = [dict() for _ in range(24)]
    measures = (
        COUNT,
        AMOUNT_SUM,
        RESOLUTION_TIME_COUNT,
        RESOLUTION_TIME_SUM_SECONDS,
        *SLA_BUCKETS,
    )
    for r in rows:
        for hour in r.read.hours:
            for measure in measures:
                value = r.row.total(measure, (hour,))
                if value:
                    sums[hour][measure] = sums[hour].get(measure, 0.0) + value
    for hour, slot in enumerate(slots):
        s = sums[hour]
        slot.alerts = _int(s.get(COUNT, 0.0))
        slot.amount_sum = s.get(AMOUNT_SUM, 0.0)
        slot.resolution_time_count = _int(s.get(RESOLUTION_TIME_COUNT, 0.0))
        slot.resolution_time_sum_seconds = s.get(RESOLUTION_TIME_SUM_SECONDS, 0.0)
        slot.within_sla_count = _int(sum(s.get(name, 0.0) for name in SLA_BUCKETS))
    return slots


def periods(read: AlertRollupRead) -> list[MetricsPeriod]:
    by_read: dict[tuple[str, str], list[PlannedRow]] = {}
    for r in read.rows:
        by_read.setdefault((r.read.level.value, r.read.period), []).append(r)
    result: list[MetricsPeriod] = []
    for planned in read.reads:
        group = by_read.get((planned.level.value, planned.period), [])
        quality = fraud_quality(group)
        result.append(
            MetricsPeriod(
                level=planned.level.value,
                period=planned.period,
                period_start=planned.period_start,
                period_end=planned.period_end,
                hours=list(planned.hours),
                partial=planned.partial,
                maturation=planned.maturation.value,
                alerts=_int(_sum(group, COUNT)),
                amount_sum=_sum(group, AMOUNT_SUM),
                decided=quality.decided,
                false_positives=quality.false_positives,
                undetected_fraud=quality.undetected_fraud,
                reviewed=quality.reviewed,
            )
        )
    return result


def warnings(read: AlertRollupRead) -> list[MetricsWarning]:
    result: list[MetricsWarning] = []
    partial = [r.period for r in read.reads if r.partial]
    if partial:
        result.append(
            MetricsWarning(
                code="partial_period",
                message=(
                    "Older than 90 days the data is only kept per month/year: "
                    "these periods are counted whole and include alerts outside "
                    "the requested range."
                ),
                periods=partial,
            )
        )
    versions = read.range.schema_versions
    if len(versions) > 1:
        result.append(
            MetricsWarning(
                code="schema_changed",
                message=(
                    "The range spans more than one amount-tier set (versions "
                    + ", ".join(versions)
                    + "): each alert keeps the tier it was classified with on arrival."
                ),
            )
        )
    maturing = [r.period for r in read.reads if r.maturation.value != "stable"]
    if maturing:
        result.append(
            MetricsWarning(
                code="fraud_label_maturing",
                message=(
                    "False positives and undetected fraud may still change for "
                    "these periods: fraud_label corrections arrive up to ~6 months "
                    "later (~98 % within 4 days)."
                ),
                periods=maturing,
            )
        )
    return result

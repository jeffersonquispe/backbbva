"""ReconcileAlertRollups (R7): the nightly safety net for the alert rollups.

Recomputes, from the alert snapshots, every alert day row of the last 90
days and every alert month row of the last 6 months, compares them with the
stored rows and corrects the ones that differ. Reports how many rows
drifted (log + aria.metrics.rollup_drift via MonitoringPort). Snapshots are
the source of truth here; it never writes a snapshot - except for alerts
that have none at all (every live event for them was lost), which are
rebuilt from their stored history through BackfillAlertMetrics (R6) first.

Second rollup writer, by design - and how it avoids racing the live one
(RecordAlertMetricsEvent, which keeps ADDing deltas while this runs):

1. Every write to a row bumps its revision (`rev`, ADD 1 in the same
   update), the live transaction included.
2. Pass 1 compares the period's stored rows with its snapshots and only
   flags candidate rows (read order doesn't matter, nothing is written).
3. For a period with candidates it waits `settle_seconds`, reads the rows
   again, then re-reads the snapshots. A candidate is corrected only if its
   revision is unchanged since pass 1 and it still differs; the write is
   conditioned on that same revision (MetricsRollupRepository.correct).

So no live write touched the row between the pass-1 read and the
correction: every delta it holds was committed before pass 1, i.e. at
least `settle_seconds` before the snapshots were re-read through the
created_day index (eventually consistent, sub-second lag) - the snapshots
and the row describe the same state. A live write that lands any time in
between changes the revision, the correction is skipped (counted in
skipped_concurrent) and the next run retries. A correction is a SET of the
absolute value, not an ADD, so it can never double count; a later live ADD
lands on top of the corrected value, which is right."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.application.dtos.metrics_maintenance_dtos import (
    ReconcileAlertRollupsInput,
    ReconcileAlertRollupsOutput,
)
from src.application.ports.alert_port import AlertRepository
from src.application.ports.metrics_rollup_port import (
    DAY_LEVEL_RETENTION_DAYS,
    MetricsDataType,
    MetricsRollupRepository,
    RollupKey,
    RollupLevel,
    RollupRow,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.use_cases.metrics.alert_rollup_contribution import contribution
from src.application.use_cases.metrics.backfill_alert_metrics import (
    BackfillAlertMetrics,
)

logger = logging.getLogger(__name__)

Dimensions = tuple[tuple[str, str], ...]
# Per row (dimensions): per measure, its 24 hour-of-day slots.
Expected = dict[Dimensions, dict[str, list[float]]]

_TOLERANCE = 1e-6


def _same(left: float, right: float) -> bool:
    return abs(left - right) <= _TOLERANCE * max(1.0, abs(right))


def rows_differ(stored: dict[str, list[float]], expected: dict[str, list[float]]) -> bool:
    for measure in set(stored) | set(expected):
        left = stored.get(measure) or [0.0] * 24
        right = expected.get(measure) or [0.0] * 24
        if any(not _same(left[h], right[h]) for h in range(24)):
            return True
    return False


def _merge(into: Expected, part: Expected) -> None:
    for dims, measures in part.items():
        target = into.setdefault(dims, {})
        for measure, slots in measures.items():
            current = target.setdefault(measure, [0.0] * 24)
            for hour, value in enumerate(slots):
                current[hour] += value


def _month_days(year: int, month: int, last: date) -> list[date]:
    day = date(year, month, 1)
    days = []
    while day.month == month and day <= last:
        days.append(day)
        day += timedelta(days=1)
    return days


class ReconcileAlertRollups:
    def __init__(
        self,
        alert_repository: AlertRepository,
        rollup_repository: MetricsRollupRepository,
        monitoring: MonitoringPort,
        timezone_name: str,
        backfill: BackfillAlertMetrics | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        settle_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._alerts = alert_repository
        self._rollups = rollup_repository
        self._monitoring = monitoring
        self._zone = ZoneInfo(timezone_name)
        self._backfill = backfill
        self._clock = clock
        self._settle_seconds = settle_seconds
        self._sleep = sleep

    def execute(
        self, input: ReconcileAlertRollupsInput | None = None
    ) -> ReconcileAlertRollupsOutput:
        input = input or ReconcileAlertRollupsInput()
        output = ReconcileAlertRollupsOutput()
        today = self._clock().astimezone(self._zone).date()
        day_window = {
            today - timedelta(days=age)
            for age in range(min(input.day_window, DAY_LEVEL_RETENTION_DAYS))
        }
        months: list[tuple[int, int]] = []
        year, month = today.year, today.month
        for _ in range(input.month_window):
            months.append((year, month))
            year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        months.reverse()
        month_days = {ym: _month_days(*ym, today) for ym in months}

        # Pass 1, day level; each day's expected rows are cached so the month
        # level doesn't read the same snapshots twice.
        cache: dict[date, Expected] = {}
        all_days = sorted(day_window | {d for days in month_days.values() for d in days})
        day_drift = 0
        for day in all_days:
            # Snapshots first (backfilling any missing one), then the rows:
            # a backfill writes the rows too, so reading them afterwards
            # keeps it from showing up as drift.
            cache[day] = self._expected([day], output)
            if day in day_window:
                stored = self._stored(RollupLevel.DAY, day.isoformat())
                output.days_checked += 1
                day_drift += self._check(
                    RollupLevel.DAY, day.isoformat(), [day], stored, cache[day], output
                )

        month_drift = 0
        for (year, month), days in month_days.items():
            period = f"{year:04d}-{month:02d}"
            stored = self._stored(RollupLevel.MONTH, period)
            expected: Expected = {}
            for day in days:
                _merge(expected, cache[day])
            output.months_checked += 1
            month_drift += self._check(
                RollupLevel.MONTH, period, days, stored, expected, output
            )

        output.drift_by_level = {
            RollupLevel.DAY.value: day_drift,
            RollupLevel.MONTH.value: month_drift,
        }
        for level, drift in output.drift_by_level.items():
            self._monitoring.record_rollup_drift(MetricsDataType.ALERT.value, level, drift)
        log = logger.warning if output.drift else logger.info
        log(
            "Alert rollup reconciliation: drift=%s (day=%s month=%s) corrected=%s "
            "skipped_concurrent=%s rows_checked=%s days=%s months=%s "
            "snapshots_backfilled=%s",
            output.drift,
            day_drift,
            month_drift,
            output.corrected,
            output.skipped_concurrent,
            output.rows_checked,
            output.days_checked,
            output.months_checked,
            output.snapshots_backfilled,
        )
        return output

    # --- internals ---------------------------------------------------------------

    def _stored(self, level: RollupLevel, period: str) -> dict[Dimensions, RollupRow]:
        rows = self._rollups.query(MetricsDataType.ALERT, level, [period])
        return {row.key.dimensions: row for row in rows}

    def _expected(
        self, days: list[date], output: ReconcileAlertRollupsOutput | None
    ) -> Expected:
        expected: Expected = {}
        for day in days:
            for alert in self._alerts.list_by_created_day(day):
                snapshot = alert.metrics
                if snapshot is None and self._backfill is not None and output is not None:
                    if self._backfill.backfill_alert(alert):
                        output.snapshots_backfilled += 1
                    refreshed = self._alerts.get(alert.id)
                    snapshot = refreshed.metrics if refreshed else None
                if snapshot is None:
                    continue  # never recorded: contributes to no row
                part = contribution(snapshot, alert.created_at, self._zone)
                slots = expected.setdefault(part.dimensions, {})
                for measure, value in part.measures.items():
                    slots.setdefault(measure, [0.0] * 24)[part.hour] += value
        return expected

    def _check(
        self,
        level: RollupLevel,
        period: str,
        days: list[date],
        stored: dict[Dimensions, RollupRow],
        expected: Expected,
        output: ReconcileAlertRollupsOutput,
    ) -> int:
        """Pass 1 for one period, then confirmation + correction of its
        candidates. Returns the confirmed drifting rows."""
        output.rows_checked += len(set(stored) | set(expected))
        candidates = {
            dims: (stored[dims].revision if dims in stored else None)
            for dims in set(stored) | set(expected)
            if rows_differ(
                stored[dims].measures if dims in stored else {}, expected.get(dims, {})
            )
        }
        if not candidates:
            return 0
        self._sleep(self._settle_seconds)
        stored_again = self._stored(level, period)
        expected_again = self._expected(days, None)
        drift = 0
        for dims, first_revision in candidates.items():
            row = stored_again.get(dims)
            revision = row.revision if row is not None else None
            if revision != first_revision:
                output.skipped_concurrent += 1
                continue
            target = expected_again.get(dims, {})
            if not rows_differ(row.measures if row is not None else {}, target):
                continue  # pass 1 saw a not-yet-propagated snapshot
            drift += 1
            key = RollupKey(MetricsDataType.ALERT, level, period, dims)
            if self._rollups.correct(key, target, revision):
                output.corrected += 1
            else:
                output.skipped_concurrent += 1
        return drift

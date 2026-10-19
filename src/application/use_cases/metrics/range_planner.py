"""Range planner (A1): which metrics-rollup rows to read for a time range.

Pure function, no I/O, no infrastructure imports. The timezone is a
parameter (callers pass the operations timezone, America/Bogota today);
application code must not read infrastructure config.

Rollup model (see docs/OBSERVABILITY_STRATEGY.md, "Niveles de agregado"):

- Levels ``day`` / ``month`` / ``year``. Day rows only exist for dates less
  than ``DAY_LEVEL_RETENTION_DAYS`` (90, from ``metrics_rollup_port``) days
  old (age 0..89, age = local today - date). Month and year rows always
  exist.
- Every row carries 24 hour-of-day slots (0-23, local time). There is no
  hour level: "last 24 h" is read as today's slots up to the current hour
  plus yesterday's slots from the next hour on (24 slots total).

Behaviors chosen at the edges (all documented in ``plan``'s docstring):

1. **Slot inclusion.** ``[from_, to)`` is half-open and snapped to whole
   hour slots: a slot is read iff its local start instant falls in
   ``[from_, min(to, now))``. So the slot containing ``now`` (live, partial
   hour) is read, a leading partial hour is not. ``to`` is clamped to
   ``now`` (future slots hold no data). A range shorter than an hour that
   contains no slot start yields an empty plan.
2. **Inside the 90-day window** each covered date is a ``day`` read with its
   exact hour subset.
3. **Outside the window** dates are read through ``month`` rows. A month
   row can't be split by day nor filtered by hour for a single day, so it is
   always read with all 24 hours; if the range does not cover the whole
   month with all 24 hours, the read is flagged ``partial=True`` (it
   over-includes data outside the range, the API must warn).
4. **Boundary month** (a month that contains both out-of-window and
   in-window covered dates): read as a single ``month`` row (never mixed
   with day rows of the same month, which would double count), ``partial``
   unless fully covered.
5. **Years**: a calendar year fully covered (every date, all 24 hours) whose
   last day (Dec 31) is outside the 90-day window is read as one ``year``
   row instead of 12 month rows. Partial years are never read as years.
6. **Maturation** is computed from the youngest date the row aggregates
   (``min(period end, local today)``), using the configured day and month
   thresholds passed to ``plan``.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from enum import Enum
from zoneinfo import ZoneInfo

from src.application.errors import ValidationError
from src.application.ports.metrics_rollup_port import (
    DAY_LEVEL_RETENTION_DAYS,
    RollupLevel,
)


class Maturation(str, Enum):
    MATURING = "maturing"  # < 4 days old: fraud labels still arriving (~98 %)
    MAY_VARY = "may_vary"  # < 6 months old: late corrections possible (~2 %)
    STABLE = "stable"


ALL_HOURS: tuple[int, ...] = tuple(range(24))


@dataclass(frozen=True)
class PlannedRead:
    """One rollup row to read.

    ``period`` is ``YYYY-MM-DD`` (day), ``YYYY-MM`` (month) or ``YYYY``
    (year). ``period_start``/``period_end`` are the inclusive local dates
    the row aggregates. ``hours`` is the sorted hour-of-day subset to sum.
    ``partial`` means the row covers more than the requested range (it
    over-includes); the caller should surface a warning.
    """

    level: RollupLevel
    period: str
    period_start: date
    period_end: date
    hours: tuple[int, ...]
    partial: bool
    maturation: Maturation


def plan(
    from_: datetime,
    to: datetime,
    now: datetime,
    tz: tzinfo | str,
    maturing_days: int = 4,
    stable_months: int = 6,
) -> list[PlannedRead]:
    """Return the rollup rows to read for ``[from_, to)``, in chronological order.

    All three datetimes must be timezone-aware. ``tz`` is the bucketing
    timezone (a ``tzinfo`` or an IANA name). Raises ``ValueError`` when
    ``from_ > to`` or a datetime is naive. ``from_ == to`` returns ``[]``.

    See the module docstring for boundary rules (slot inclusion, 90-day
    window, partial months, years, and maturation).
    """
    for name, value in (("from_", from_), ("to", to), ("now", now)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValidationError(f"{name} must be timezone-aware")
    if from_ > to:
        raise ValidationError("from_ must be <= to")
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz

    today = now.astimezone(zone).date()
    effective_to = min(to, now)
    if from_ >= effective_to:
        return []

    covered = _covered_hours_by_date(from_, effective_to, zone)
    if not covered:
        return []

    window_start = today - timedelta(days=DAY_LEVEL_RETENTION_DAYS - 1)
    reads: list[PlannedRead] = []

    # Months that contain at least one covered out-of-window date.
    rolled_months = sorted({(d.year, d.month) for d in covered if d < window_start})
    rolled_month_set = set(rolled_months)

    # Full years entirely outside the window collapse to a year row.
    full_years: set[int] = set()
    for year in sorted({y for y, _ in rolled_months}):
        last = date(year, 12, 31)
        if last < window_start and _fully_covered(date(year, 1, 1), last, covered):
            full_years.add(year)

    for year in sorted(full_years):
        start, end = date(year, 1, 1), date(year, 12, 31)
        reads.append(
            PlannedRead(
                level=RollupLevel.YEAR,
                period=f"{year:04d}",
                period_start=start,
                period_end=end,
                hours=ALL_HOURS,
                partial=False,
                maturation=_maturation(end, today, maturing_days, stable_months),
            )
        )

    for year, month in rolled_months:
        if year in full_years:
            continue
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        reads.append(
            PlannedRead(
                level=RollupLevel.MONTH,
                period=f"{year:04d}-{month:02d}",
                period_start=start,
                period_end=end,
                hours=ALL_HOURS,
                partial=not _fully_covered(start, end, covered),
                maturation=_maturation(
                    min(end, today), today, maturing_days, stable_months
                ),
            )
        )

    for day, hours in sorted(covered.items()):
        if (day.year, day.month) in rolled_month_set:
            continue  # already read through its month (or year) row
        reads.append(
            PlannedRead(
                level=RollupLevel.DAY,
                period=day.isoformat(),
                period_start=day,
                period_end=day,
                hours=hours,
                partial=False,
                maturation=_maturation(day, today, maturing_days, stable_months),
            )
        )

    reads.sort(key=lambda r: (r.period_start, r.period_end))
    return reads


def _covered_hours_by_date(
    from_: datetime, to: datetime, zone: tzinfo
) -> dict[date, tuple[int, ...]]:
    """Map local date -> hour slots whose local start lies in ``[from_, to)``.

    Iterates in wall-clock local time (naive), which is exact for zones
    without DST such as America/Bogota.
    """
    local_from = from_.astimezone(zone).replace(tzinfo=None)
    local_to = to.astimezone(zone).replace(tzinfo=None)

    first = local_from.replace(minute=0, second=0, microsecond=0)
    if first < local_from:
        first += timedelta(hours=1)
    if first >= local_to:
        return {}
    # Last slot start strictly before local_to.
    last = local_to.replace(minute=0, second=0, microsecond=0)
    if last == local_to:
        last -= timedelta(hours=1)

    result: dict[date, tuple[int, ...]] = {}
    day = first.date()
    while day <= last.date():
        lo = first.hour if day == first.date() else 0
        hi = last.hour if day == last.date() else 23
        result[day] = tuple(range(lo, hi + 1))
        day += timedelta(days=1)
    return result


def _fully_covered(
    start: date, end: date, covered: dict[date, tuple[int, ...]]
) -> bool:
    day = start
    while day <= end:
        if covered.get(day) != ALL_HOURS:
            return False
        day += timedelta(days=1)
    return True


def _maturation(
    youngest: date, today: date, maturing_days: int, stable_months: int
) -> Maturation:
    if (today - youngest).days < maturing_days:
        return Maturation.MATURING
    if youngest > _subtract_months(today, stable_months):
        return Maturation.MAY_VARY
    return Maturation.STABLE


def _subtract_months(value: date, months: int) -> date:
    total = value.year * 12 + (value.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

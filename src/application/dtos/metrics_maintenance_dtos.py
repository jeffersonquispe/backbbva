from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from src.application.ports.metrics_rollup_port import DAY_LEVEL_RETENTION_DAYS


@dataclass
class BackfillAlertMetricsInput:
    """Inclusive range of alert days (operations timezone, Bogota)."""

    from_day: date
    to_day: date


@dataclass
class BackfillAlertMetricsOutput:
    days: int = 0
    alerts_seen: int = 0
    # Alerts that got their first snapshot (and rollup contribution) now.
    backfilled: int = 0
    # Alerts that already had a snapshot - left untouched.
    already_recorded: int = 0


# R7 windows: day rows for the last 90 days (every day still written by the
# live path), month rows for the current month and the 5 before it.
RECONCILE_MONTHS = 6


@dataclass
class ReconcileAlertRollupsInput:
    day_window: int = DAY_LEVEL_RETENTION_DAYS
    month_window: int = RECONCILE_MONTHS


@dataclass
class ReconcileAlertRollupsOutput:
    days_checked: int = 0
    months_checked: int = 0
    rows_checked: int = 0
    # Rows whose stored measures differed from the snapshots (confirmed on a
    # second read), per level - reported as aria.metrics.rollup_drift.
    drift_by_level: dict[str, int] = field(default_factory=dict)
    corrected: int = 0
    # Drifting rows a live write touched while we were checking: left for
    # the next run instead of risking a lost/double-counted live delta.
    skipped_concurrent: int = 0
    # Alerts with no snapshot at all, rebuilt from stored history (R6).
    snapshots_backfilled: int = 0

    @property
    def drift(self) -> int:
        return sum(self.drift_by_level.values())


@dataclass
class LiveAlertFunnelOutput:
    """R9 "Tiempo real": alerts in each live state right now."""

    received: int
    processing: int
    escalated: int
    # Voicebot calls in progress (active voicebot reservations): their
    # alerts are already CLOSED with a pending mark, so no alert status
    # represents them.
    voicebot_in_call: int
    measured_at: datetime

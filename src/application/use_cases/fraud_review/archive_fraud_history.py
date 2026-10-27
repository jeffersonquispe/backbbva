"""Fraud-history retention: alerts (with their fraud-label reviews and notes)
stay hot in DynamoDB for ``hot_days``, then move day by day to cold object
storage. The cold copy's own lifetime (the legal retention period) is an
object-storage retention rule on the archive prefix, not this use case.

``hot_days`` can never undercut the windows that still read or correct old
alerts: the 6-month fraud maturation (late fraud_label corrections, mature
samples) and the nightly month-level rollup reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from src.application.dtos.metrics_maintenance_dtos import RECONCILE_MONTHS
from src.application.ports.clock_port import Clock
from src.application.ports.fraud_history_archive_port import (
    FraudHistoryArchivePort,
    FraudHistoryDayArchive,
)

# Six reconciled months plus the current one, at 31 days each.
MIN_HOT_DAYS = (RECONCILE_MONTHS + 1) * 31


@dataclass(frozen=True)
class ArchiveFraudHistoryOutput:
    dry_run: bool
    days: list[FraudHistoryDayArchive]

    @property
    def alerts(self) -> int:
        return sum(day.alerts for day in self.days)

    @property
    def deleted(self) -> int:
        return sum(day.deleted for day in self.days)


class ArchiveFraudHistory:
    def __init__(
        self,
        archive: FraudHistoryArchivePort,
        clock: Clock,
        timezone_name: str,
    ) -> None:
        self._archive = archive
        self._clock = clock
        self._zone = ZoneInfo(timezone_name)

    def execute(
        self, *, hot_days: int, scan_days: int, dry_run: bool = True
    ) -> ArchiveFraudHistoryOutput:
        """Archive the ``scan_days`` creation days right before the hot
        window, oldest first. Daily runs then advance one day each; a wider
        ``scan_days`` catches up a backlog."""
        if hot_days < MIN_HOT_DAYS:
            raise ValueError(f"hot_days must be >= {MIN_HOT_DAYS}")
        if scan_days < 1:
            raise ValueError("scan_days must be >= 1")
        today = self._clock.now().astimezone(self._zone).date()
        newest = today - timedelta(days=hot_days + 1)
        days = [
            self._archive.archive_day(newest - timedelta(days=age), dry_run=dry_run)
            for age in reversed(range(scan_days))
        ]
        return ArchiveFraudHistoryOutput(dry_run=dry_run, days=days)

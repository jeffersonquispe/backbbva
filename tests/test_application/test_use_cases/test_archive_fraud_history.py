from datetime import UTC, date, datetime

import pytest

from src.application.ports.clock_port import Clock
from src.application.ports.fraud_history_archive_port import (
    FraudHistoryArchivePort,
    FraudHistoryDayArchive,
)
from src.application.use_cases.fraud_review.archive_fraud_history import (
    MIN_HOT_DAYS,
    ArchiveFraudHistory,
)

# 03:30 Bogotá on 2026-10-27 is 08:30 UTC; 02:00 UTC would still be the 26th.
NOW = datetime(2026, 10, 27, 8, 30, tzinfo=UTC)


class FixedClock(Clock):
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class RecordingFraudHistoryArchivePort(FraudHistoryArchivePort):
    def __init__(self, alerts_per_day: dict[date, int] | None = None) -> None:
        self.alerts_per_day = alerts_per_day or {}
        self.calls: list[tuple[date, bool]] = []

    def archive_day(self, created_day: date, *, dry_run: bool) -> FraudHistoryDayArchive:
        self.calls.append((created_day, dry_run))
        alerts = self.alerts_per_day.get(created_day, 0)
        return FraudHistoryDayArchive(
            created_day=created_day,
            alerts=alerts,
            reviews=alerts,
            held=0,
            deleted=0 if dry_run else alerts,
            object_key=None,
            sha256=None,
        )


def _use_case(archive: RecordingFraudHistoryArchivePort, now: datetime = NOW):
    return ArchiveFraudHistory(archive, FixedClock(now), "America/Bogota")


def test_archives_the_days_right_before_the_hot_window_oldest_first() -> None:
    archive = RecordingFraudHistoryArchivePort()

    _use_case(archive).execute(hot_days=365, scan_days=3, dry_run=False)

    # Today (Bogotá) 2026-10-27 - 366 days = 2025-10-26 is the newest day out.
    assert archive.calls == [
        (date(2025, 10, 24), False),
        (date(2025, 10, 25), False),
        (date(2025, 10, 26), False),
    ]


def test_bogota_date_decides_the_window_not_utc() -> None:
    archive = RecordingFraudHistoryArchivePort()
    # 2026-10-27 02:00 UTC is still 2026-10-26 in Bogotá.
    early = datetime(2026, 10, 27, 2, 0, tzinfo=UTC)

    _use_case(archive, early).execute(hot_days=365, scan_days=1)

    assert archive.calls == [(date(2025, 10, 25), True)]


def test_output_totals_alerts_and_deletions() -> None:
    archive = RecordingFraudHistoryArchivePort(
        {date(2025, 10, 25): 4, date(2025, 10, 26): 2}
    )

    output = _use_case(archive).execute(hot_days=365, scan_days=2, dry_run=False)

    assert output.alerts == 6 and output.deleted == 6 and output.dry_run is False


def test_dry_run_is_the_default_and_deletes_nothing() -> None:
    archive = RecordingFraudHistoryArchivePort({date(2025, 10, 26): 3})

    output = _use_case(archive).execute(hot_days=365, scan_days=1)

    assert archive.calls == [(date(2025, 10, 26), True)]
    assert output.alerts == 3 and output.deleted == 0


@pytest.mark.parametrize(
    ("hot_days", "scan_days"), [(MIN_HOT_DAYS - 1, 1), (365, 0)]
)
def test_rejects_windows_that_would_archive_live_data(hot_days, scan_days) -> None:
    archive = RecordingFraudHistoryArchivePort()

    with pytest.raises(ValueError):
        _use_case(archive).execute(hot_days=hot_days, scan_days=scan_days)
    assert archive.calls == []


def test_minimum_hot_window_covers_maturation_and_reconciliation() -> None:
    # Six months of late fraud_label corrections and month-level rollup
    # reconciliation still read these alerts from DynamoDB.
    assert MIN_HOT_DAYS >= 7 * 31

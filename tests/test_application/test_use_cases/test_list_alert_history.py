"""A3: ListAlertHistory - newest first, paged by created day through the
index (page_by_created_day), filters on the snapshot, opaque cursor."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from src.application.dtos.alert_history_dtos import ListAlertHistoryInput
from src.application.ports.alert_port import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertStatus,
    Mark,
)
from src.application.use_cases.alerts import list_alert_history as module
from src.application.use_cases.alerts.list_alert_history import (
    InvalidHistoryCursorError,
    ListAlertHistory,
)

TZ = "America/Bogota"
ZONE = ZoneInfo(TZ)
NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


class InMemoryAlertRepository:
    """Serves page_by_created_day like the CreatedDayIdx query; records the
    calls so the test can assert no full-table read happens."""

    def __init__(self, alerts: list[AlertRecord]) -> None:
        self.alerts = alerts
        self.page_calls: list[date] = []

    def page_by_created_day(self, created_day: date, *, before, limit):
        self.page_calls.append(created_day)
        day = [
            a
            for a in self.alerts
            if a.created_at.astimezone(ZONE).date() == created_day
            and (before is None or a.created_at < before)
        ]
        return sorted(day, key=lambda a: a.created_at, reverse=True)[:limit]


def _alert(
    created_at: datetime, channel: str = "WEB", metrics: bool = True
) -> AlertRecord:
    return AlertRecord(
        id=uuid4(),
        event_id="e",
        event_type="payment",
        status=AlertStatus.CLOSED,
        created_at=created_at,
        updated_at=created_at,
        input={"channel": channel, "entrypoint": "PSE", "amount": 10},
        metrics=(
            AlertMetricsSnapshot(
                channel=channel,
                status=AlertStatus.CLOSED,
                mark=Mark.FRAUD,
                fraud_label=Mark.NO_FRAUD,
                marked_at=created_at + timedelta(minutes=3),
                fraud_reviewed_at=created_at + timedelta(days=2),
                fraud_review_count=1,
                snapshot_version=3,
            )
            if metrics
            else None
        ),
    )


def _use_case(alerts) -> ListAlertHistory:
    return ListAlertHistory(alerts, TZ, clock=lambda: NOW)


def _all_pages(use_case, **kwargs) -> tuple[list[UUID], int]:
    ids, cursor, pages = [], None, 0
    while True:
        out = use_case.execute(ListAlertHistoryInput(cursor=cursor, **kwargs))
        pages += 1
        ids.extend(item.alert.id for item in out.items)
        cursor = out.next_cursor
        if cursor is None:
            return ids, pages


def test_pages_newest_first_across_days_without_gaps_or_repeats() -> None:
    alerts = [_alert(NOW - timedelta(hours=7 * i + 1)) for i in range(40)]  # ~12 days
    repo = InMemoryAlertRepository(alerts)

    ids, pages = _all_pages(
        _use_case(repo), from_=NOW - timedelta(days=30), to=NOW, limit=7
    )

    expected = [a.id for a in sorted(alerts, key=lambda a: a.created_at, reverse=True)]
    assert ids == expected
    assert pages >= 6


def test_filters_apply_to_the_snapshot_and_payload_fallback() -> None:
    web = _alert(NOW - timedelta(hours=2), channel="WEB")
    app = _alert(NOW - timedelta(hours=3), channel="APP")
    legacy = _alert(NOW - timedelta(hours=4), channel="APP", metrics=False)
    repo = InMemoryAlertRepository([web, app, legacy])

    out = _use_case(repo).execute(ListAlertHistoryInput(filters={"channel": ["APP"]}))

    assert [i.alert.id for i in out.items] == [app.id, legacy.id]
    first, second = out.items
    assert first.has_snapshot and first.metrics.fraud_label == Mark.NO_FRAUD
    assert first.metrics.fraud_review_count == 1
    assert not second.has_snapshot and second.metrics.mark == Mark.PENDING
    assert second.metrics.amount == 10


def test_range_bounds_are_half_open_and_respected() -> None:
    inside = _alert(NOW - timedelta(days=2))
    at_to = _alert(NOW - timedelta(days=1))
    before_from = _alert(NOW - timedelta(days=3, seconds=1))
    repo = InMemoryAlertRepository([inside, at_to, before_from])

    out = _use_case(repo).execute(
        ListAlertHistoryInput(from_=NOW - timedelta(days=3), to=NOW - timedelta(days=1))
    )

    assert [i.alert.id for i in out.items] == [inside.id]
    assert out.next_cursor is None


def test_a_long_selective_range_returns_a_short_page_with_a_cursor(monkeypatch) -> None:
    monkeypatch.setattr(module, "MAX_DAYS_PER_PAGE", 5)
    old = _alert(NOW - timedelta(days=20), channel="APP")
    repo = InMemoryAlertRepository([old, _alert(NOW - timedelta(hours=1))])
    use_case = _use_case(repo)

    first = use_case.execute(ListAlertHistoryInput(filters={"channel": ["APP"]}))
    assert first.items == [] and first.next_cursor is not None
    assert len(repo.page_calls) == 5

    ids, _ = _all_pages(use_case, filters={"channel": ["APP"]})
    assert ids == [old.id]


def test_bad_cursor_and_filter_are_rejected() -> None:
    use_case = _use_case(InMemoryAlertRepository([]))
    with pytest.raises(InvalidHistoryCursorError):
        use_case.execute(ListAlertHistoryInput(cursor="not-a-cursor"))
    with pytest.raises(ValueError):
        use_case.execute(ListAlertHistoryInput(filters={"customer_id": ["x"]}))

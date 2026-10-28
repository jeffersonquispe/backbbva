from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.domain.alerts.transaction_history_selection import (
    parse_event_time,
    select_transaction_history,
    summarize_transaction_history,
)


@dataclass
class _Entry:
    event_id: str
    event_time: str
    amount: float
    channel: str


_HISTORY = [
    _Entry("e1", "2026-09-01T10:00:00Z", 10.0, "web"),
    _Entry("e2", "2026-09-20T10:00:00Z", 20.0, "app"),
    _Entry("e3", "2026-09-27T10:00:00Z", 30.0, "app"),
    _Entry("e4", "not-a-date", 40.0, "atm"),
]
_REFERENCE = datetime(2026, 9, 28, tzinfo=UTC)


def _select(**overrides):
    kwargs = dict(
        columns=[], window_days=0, max_transactions=0, reference_time=_REFERENCE
    )
    kwargs.update(overrides)
    return select_transaction_history(_HISTORY, **kwargs)


def test_no_limits_returns_every_entry_most_recent_first() -> None:
    rows = _select()
    assert [row["event_id"] for row in rows] == ["e3", "e2", "e1", "e4"]


def test_window_keeps_only_entries_inside_it_and_drops_unparseable() -> None:
    rows = _select(window_days=10)
    assert [row["event_id"] for row in rows] == ["e3", "e2"]


def test_max_transactions_keeps_the_most_recent() -> None:
    rows = _select(max_transactions=1)
    assert [row["event_id"] for row in rows] == ["e3"]


def test_columns_project_each_row() -> None:
    rows = _select(columns=["amount", "channel"], max_transactions=1)
    assert rows == [{"amount": 30.0, "channel": "app"}]


def test_window_anchors_on_latest_event_without_reference_time() -> None:
    # A replayed alert from the past must not be windowed against "now".
    rows = _select(window_days=8, reference_time=None)
    assert [row["event_id"] for row in rows] == ["e3", "e2"]


def test_parse_event_time_accepts_iso_and_epoch_millis() -> None:
    assert parse_event_time("2026-09-27T10:00:00Z") == datetime(
        2026, 9, 27, 10, tzinfo=UTC
    )
    assert parse_event_time(1790503200000) == datetime(2026, 9, 27, 10, tzinfo=UTC)
    assert parse_event_time("garbage") is None


def test_summary_keeps_schema_size_period_and_only_the_most_recent_sample() -> None:
    summary = summarize_transaction_history(_HISTORY, sample_size=2)

    assert summary["total_rows"] == 4
    assert summary["columns"] == ["event_id", "event_time", "amount", "channel"]
    assert [row["event_id"] for row in summary["sample"]] == ["e3", "e2"]
    assert summary["first_event_time"].startswith("2026-09-01")
    assert summary["last_event_time"].startswith("2026-09-27")
    assert "2 transacciones más recientes de 4" in summary["note"]


def test_summary_of_an_empty_history_has_no_sample_or_period() -> None:
    summary = summarize_transaction_history([], sample_size=5)

    assert summary["total_rows"] == 0
    assert summary["sample"] == []
    assert summary["first_event_time"] is None

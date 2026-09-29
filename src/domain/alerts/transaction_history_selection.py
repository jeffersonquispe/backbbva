"""Slice of an alert's transaction history exposed to an agent step.

Pure function, no framework imports - configured per segment by
DetectorConfig's history_* fields ("selector sobre la lista de
transacciones").
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any


def parse_event_time(value: Any) -> datetime | None:
    """ISO-8601 (with or without "Z") or epoch seconds/milliseconds."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or str(value).isdigit():
        number = float(value)
        # Heuristic: anything past year ~2286 in seconds is milliseconds.
        parsed = datetime.fromtimestamp(
            number / 1000 if number > 1e10 else number, tz=timezone.utc
        )
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def select_transaction_history(
    entries: list[Any],
    *,
    columns: list[str],
    window_days: int,
    max_transactions: int,
    reference_time: datetime | None,
) -> list[dict[str, Any]]:
    """Filter to the last `window_days` before `reference_time`, keep the
    most recent `max_transactions`, project to `columns`.

    0 disables the corresponding limit; empty `columns` keeps every field.
    With a window active, entries whose event_time can't be parsed are
    dropped (they can't be placed inside the window). With no
    reference_time, the most recent parseable event_time is used, so
    replayed/historical alerts aren't windowed against wall-clock "now".
    """
    rows = [
        dataclasses.asdict(entry) if dataclasses.is_dataclass(entry) else dict(entry)
        for entry in entries
    ]
    timed = [(parse_event_time(row.get("event_time")), row) for row in rows]

    if window_days > 0:
        anchor = reference_time or max(
            (time for time, _ in timed if time is not None), default=None
        )
        if anchor is None:
            timed = []
        else:
            start = anchor - timedelta(days=window_days)
            timed = [
                (time, row) for time, row in timed
                if time is not None and start <= time <= anchor
            ]

    oldest = datetime.min.replace(tzinfo=timezone.utc)
    timed.sort(key=lambda item: item[0] or oldest, reverse=True)
    if max_transactions > 0:
        timed = timed[:max_transactions]

    selected = [row for _, row in timed]
    if columns:
        selected = [{column: row.get(column) for column in columns} for row in selected]
    return selected

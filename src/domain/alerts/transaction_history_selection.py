"""Slice of an alert's transaction history exposed to an agent step.

Pure function, no framework imports - configured per segment by
DetectorConfig's history_* fields ("selector sobre la lista de
transacciones").
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
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
            number / 1000 if number > 1e10 else number, tz=UTC
        )
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
        dataclasses.asdict(entry)
        if dataclasses.is_dataclass(entry) and not isinstance(entry, type)
        else dict(entry)
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
                (time, row)
                for time, row in timed
                if time is not None and start <= time <= anchor
            ]

    oldest = datetime.min.replace(tzinfo=UTC)
    timed.sort(key=lambda item: item[0] or oldest, reverse=True)
    if max_transactions > 0:
        timed = timed[:max_transactions]

    selected = [row for _, row in timed]
    if columns:
        selected = [{column: row.get(column) for column in columns} for row in selected]
    return selected


def summarize_transaction_history(
    entries: list[Any], *, sample_size: int
) -> dict[str, Any]:
    """Compact view of a transaction history for an LLM prompt.

    Schema (column names), size, covered period and the `sample_size` most
    recent rows - never the whole list. Exact figures over the full history
    come from the history analysis, which runs on the data, not in the prompt.
    """
    rows = [
        dataclasses.asdict(entry)
        if dataclasses.is_dataclass(entry) and not isinstance(entry, type)
        else dict(entry)
        for entry in entries
    ]
    oldest = datetime.min.replace(tzinfo=UTC)
    timed = sorted(
        ((parse_event_time(row.get("event_time")), row) for row in rows),
        key=lambda item: item[0] or oldest,
        reverse=True,
    )
    times = [time for time, _ in timed if time is not None]
    sample = [row for _, row in timed[: max(sample_size, 0)]]
    return {
        "total_rows": len(rows),
        "columns": list(dict.fromkeys(key for row in rows for key in row)),
        "first_event_time": min(times).isoformat() if times else None,
        "last_event_time": max(times).isoformat() if times else None,
        "sample": sample,
        "note": (
            f"Muestra de las {len(sample)} transacciones más recientes de "
            f"{len(rows)}. El historial completo no se incluye en el prompt; "
            "el análisis de historial calcula cifras exactas sobre todos los datos."
        ),
    }

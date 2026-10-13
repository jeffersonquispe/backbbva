from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.application.ports.alert_port import AlertMetricsSnapshot, AlertRecord


@dataclass
class ListAlertHistoryInput:
    # [from_, to) on created_at; to defaults to now, from_ to to - 30 days.
    from_: datetime | None = None
    to: datetime | None = None
    # Dimension name -> accepted values (see metrics_filters.FILTER_DIMENSIONS).
    filters: dict[str, list[str]] = field(default_factory=dict)
    limit: int = 50
    cursor: str | None = None


@dataclass
class AlertHistoryItem:
    alert: AlertRecord
    # The stored snapshot, or one derived from canonical input for alerts no
    # metrics event has touched yet (has_snapshot = False).
    metrics: AlertMetricsSnapshot
    has_snapshot: bool


@dataclass
class ListAlertHistoryOutput:
    items: list[AlertHistoryItem]
    # Opaque; None when the range is exhausted.
    next_cursor: str | None

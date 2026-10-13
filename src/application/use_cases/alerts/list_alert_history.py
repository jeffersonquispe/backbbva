"""Fraud history (A3, /historico-fraude): alerts newest first, paginated by
arrival day through the created_day index (never a Scan), with the same
filters as /metrics/*, each item carrying its metrics snapshot (mark,
fraud_label, marked_at, fraud_reviewed_at, review count).

Pagination is an opaque cursor encoding where to resume: the local day and
the created_at of the last alert examined (the next page continues
strictly before it). A request reads at most MAX_DAYS_PER_PAGE days and
MAX_EXAMINED_PER_PAGE alerts, so a very selective filter over a long range
returns a short (possibly empty) page plus a cursor instead of reading the
whole range at once - keep following next_cursor until it is null."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from src.application.dtos.alert_history_dtos import (
    AlertHistoryItem,
    ListAlertHistoryInput,
    ListAlertHistoryOutput,
)
from src.application.errors import ValidationError
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.clock_port import Clock
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.metrics.metrics_filters import (
    normalize_filters,
    snapshot_matches,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    canonical_role_values,
    payload_dimensions,
)
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
)

DEFAULT_RANGE = timedelta(days=30)
MAX_LIMIT = 200
MAX_DAYS_PER_PAGE = 31
MAX_EXAMINED_PER_PAGE = 5000
_CHUNK = 200


class InvalidHistoryCursorError(ValidationError):
    pass


def encode_cursor(day: date, before: datetime | None) -> str:
    raw = json.dumps(
        {"d": day.isoformat(), "b": before.isoformat() if before else None},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[date, datetime | None]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        day = date.fromisoformat(data["d"])
        before = datetime.fromisoformat(data["b"]) if data.get("b") else None
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise InvalidHistoryCursorError("Invalid cursor") from exc
    if before is not None and before.tzinfo is None:
        raise InvalidHistoryCursorError("Invalid cursor")
    return day, before


def history_snapshot(
    alert: AlertRecord, schemas: AlertSchemaRepository | None = None
) -> tuple[AlertMetricsSnapshot, bool]:
    if alert.metrics is not None:
        return alert.metrics, True
    roles = (
        canonical_role_values(alert, schemas)
        if schemas is not None and alert.schema_version is not None
        else {
            role: alert.input.get(role) for role in ("channel", "entrypoint", "amount")
        }
    )
    channel, subchannel, amount = payload_dimensions(roles)
    return (
        AlertMetricsSnapshot(
            channel=channel,
            subchannel=subchannel,
            amount=amount,
            schema_version=alert.schema_version,
            status=alert.status,
        ),
        False,
    )


class ListAlertHistory:
    def __init__(
        self,
        alert_repository: AlertRepository,
        timezone_name: str,
        schema_repository: AlertSchemaRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._schemas = schema_repository
        self._zone: tzinfo = ZoneInfo(timezone_name)
        self._clock = resolve_clock(clock)

    def execute(self, input: ListAlertHistoryInput) -> ListAlertHistoryOutput:
        """Raises ValueError (bad range / filter) or InvalidHistoryCursorError."""
        to = input.to or self._clock.now()
        from_ = input.from_ or (to - DEFAULT_RANGE)
        for name, value in (("from", from_), ("to", to)):
            if value.tzinfo is None:
                raise ValidationError(f"{name} must be timezone-aware")
        if from_ > to:
            raise ValidationError("from must be <= to")
        filters = normalize_filters(input.filters)
        limit = max(1, min(input.limit, MAX_LIMIT))

        first_day = from_.astimezone(self._zone).date()
        # [from_, to): an alert at exactly `to` is excluded.
        day = (to - timedelta(microseconds=1)).astimezone(self._zone).date()
        before: datetime | None = to
        if input.cursor:
            day, before = decode_cursor(input.cursor)
            if before is None or before > to:
                before = to

        items: list[AlertHistoryItem] = []
        days_read = 0
        examined = 0
        while day >= first_day:
            if days_read == MAX_DAYS_PER_PAGE:
                return ListAlertHistoryOutput(items, encode_cursor(day, before))
            days_read += 1
            while True:
                chunk = self._alerts.page_by_created_day(
                    day, before=before, limit=_CHUNK
                )
                for alert in chunk:
                    before = alert.created_at
                    examined += 1
                    if alert.created_at < from_:
                        break
                    snapshot, has_snapshot = history_snapshot(alert, self._schemas)
                    if snapshot_matches(snapshot, filters):
                        items.append(AlertHistoryItem(alert, snapshot, has_snapshot))
                        if len(items) == limit:
                            return ListAlertHistoryOutput(
                                items, encode_cursor(day, before)
                            )
                    if examined >= MAX_EXAMINED_PER_PAGE:
                        return ListAlertHistoryOutput(items, encode_cursor(day, before))
                else:
                    if len(chunk) == _CHUNK:
                        continue  # more alerts left in this day
                break
            day -= timedelta(days=1)
            before = to
        return ListAlertHistoryOutput(items, None)

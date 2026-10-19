from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.alert_schema_port import (
    AlertSchemaField,
    AlertSchemaPresenceField,
    AlertSchemaPresenceReport,
    AlertSchemaRepository,
    AlertSchemaUnknownLocation,
)
from src.application.ports.alert_schema_presence_report_port import (
    AlertSchemaPresenceReportRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.runtime_defaults import resolve_clock
from src.domain.alerts.entities import (
    AlertRecord,
)


class AnalyzeAlertSchemaPresenceUseCase:
    """Build the small, privacy-safe daily schema observability snapshot."""

    def __init__(
        self,
        alerts: AlertRepository,
        schemas: AlertSchemaRepository,
        reports: AlertSchemaPresenceReportRepository,
        object_storage: ObjectStoragePort | None = None,
        *,
        timezone_name: str = "America/Bogota",
        clock: Clock | None = None,
    ) -> None:
        self._alerts = alerts
        self._schemas = schemas
        self._reports = reports
        self._object_storage = object_storage
        self._timezone = ZoneInfo(timezone_name)
        self._clock = resolve_clock(clock)

    def execute(
        self, report_day: date | None = None
    ) -> AlertSchemaPresenceReport | None:
        if report_day is None:
            report_day = self._clock.now().astimezone(
                self._timezone
            ).date() - timedelta(days=1)
        schema = self._schemas.get_active()
        if schema is None:
            return None

        alerts = self._alerts.list_by_created_day(report_day)
        previous = self._reports.list_before(report_day, limit=30)
        previous_by_field: dict[str, AlertSchemaPresenceField] = {}
        for report in previous:
            for item in report.fields:
                previous_by_field.setdefault(item.field_id, item)
        fields: list[AlertSchemaPresenceField] = []
        role_field_ids = set(schema.field_roles.values())
        schema_locations = {
            (item.data_source.value, item.field_ds_loc)
            for item in schema.fields
            if item.field_ds_loc
        }
        unknown_counts: Counter[str] = Counter()

        for alert in alerts:
            for location in _unknown_locations(alert, self._raw_payload(alert)):
                if location not in {path for source, path in schema_locations}:
                    unknown_counts[location] += 1

        for schema_field in schema.fields:
            values: list[tuple[datetime, Any]] = []
            for alert in alerts:
                value = _field_value(alert, schema_field, self._raw_payload(alert))
                if value is not _MISSING and value is not None:
                    values.append((alert.created_at, value))
            previous_count = previous_by_field.get(schema_field.id)
            fields.append(
                _field_report(
                    schema_field,
                    values,
                    len(alerts),
                    previous_count,
                    schema_field.id in role_field_ids,
                )
            )

        generated_at = self._clock.now()
        report = AlertSchemaPresenceReport(
            report_day=report_day,
            generated_at=generated_at,
            schema_version=schema.version,
            alert_count=len(alerts),
            fields=fields,
            unknown_locations=[
                AlertSchemaUnknownLocation(location=location, frequency=count)
                for location, count in sorted(
                    unknown_counts.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        )
        return self._reports.save(report)

    def _raw_payload(self, alert: AlertRecord) -> dict[str, Any] | None:
        if self._object_storage is None or alert.raw_payload_ref is None:
            return None
        try:
            return json.loads(self._object_storage.get_bytes(alert.raw_payload_ref.key))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None


_MISSING = object()


def _field_report(
    field: AlertSchemaField,
    values: list[tuple[datetime, Any]],
    total: int,
    previous: AlertSchemaPresenceField | None,
    role_assigned: bool,
) -> AlertSchemaPresenceField:
    count = len(values)
    previous_count = previous.present_count if previous else None
    trend: dict[str, object] = {
        "present_count": count,
        "previous_count": previous_count,
        "delta": None if previous_count is None else count - previous_count,
    }
    if previous_count:
        trend["change_percent"] = round(
            (count - previous_count) * 100 / previous_count, 2
        )
    sanitized_values = [_safe_example(value, field) for _, value in values]
    distribution = _distribution(field, values, role_assigned)
    return AlertSchemaPresenceField(
        field_id=field.id,
        field=field.field,
        location=field.field_ds_loc,
        present_count=count,
        last_seen=max((when for when, _ in values), default=None),
        trend=trend,
        example=sanitized_values[-1] if sanitized_values else None,
        distribution=distribution,
    )


def _distribution(
    field: AlertSchemaField, values: list[tuple[datetime, Any]], role_assigned: bool
) -> dict[str, object] | None:
    if not role_assigned:
        return None
    raw = [value for _, value in values]
    if field.type.value == "number":
        numbers = sorted(
            float(value)
            for value in raw
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        )
        return (
            {
                "kind": "numeric",
                "count": len(numbers),
                "percentiles": {
                    str(p): _percentile(numbers, p)
                    for p in ("p25", "p50", "p75", "p95")
                },
            }
            if numbers
            else {"kind": "numeric", "count": 0, "percentiles": {}}
        )
    frequencies = Counter(_safe_example(value, field) for value in raw)
    return {
        "kind": "categorical",
        "frequencies": dict(
            sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))
        ),
    }


def _percentile(values: list[float], percentile: str) -> float | None:
    if not values:
        return None
    fraction = {"p25": 0.25, "p50": 0.5, "p75": 0.75, "p95": 0.95}[percentile] * (
        len(values) - 1
    )
    lower, upper = math.floor(fraction), math.ceil(fraction)
    return round(
        values[lower] + (values[upper] - values[lower]) * (fraction - lower), 6
    )


def _safe_example(value: Any, field: AlertSchemaField) -> str:
    if field.is_sensible:
        text = str(value)
        if field.sensitivity_strategy == "anonymize":
            return "anon_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return ("*" * max(0, len(text) - 4)) + text[-4:]
    return str(value)


def _field_value(
    alert: AlertRecord, field: AlertSchemaField, raw_payload: dict[str, Any] | None
) -> Any:
    roots = []
    if field.data_source.value == "aria":
        roots = [alert.agent_output]
    elif field.data_source.value == "aric":
        roots = [raw_payload] if raw_payload else [alert.input]
    else:
        roots = [alert.input]
    for root in roots:
        value = _get_path(root, field.field_ds_loc)
        if value is not _MISSING:
            return value
        if field.field in root:
            return root[field.field]
    return _MISSING


def _get_path(root: Any, path: str) -> Any:
    if not isinstance(root, dict) or not path:
        return _MISSING
    value: Any = root
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _unknown_locations(
    alert: AlertRecord, raw_payload: dict[str, Any] | None = None
) -> set[str]:
    payload = raw_payload
    return _dotted_paths(payload) if payload else set()


def _dotted_paths(value: Any, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix} if prefix else set()
    paths: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        paths.update(_dotted_paths(child, path))
    return paths

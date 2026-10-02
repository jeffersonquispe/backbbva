"""The filters /metrics/* and /alerts/history accept, shared so both read
"segment=X" the same way: each is a rollup dimension (ALERT_DIMENSIONS),
matched on the snapshot's normalized value (enum value, "unknown" when
missing - so "segment=unknown" selects alerts with no segment)."""
from __future__ import annotations

from src.application.ports.alert_port import AlertMetricsSnapshot
from src.application.use_cases.metrics.alert_rollup_contribution import (
    alert_dimensions,
)

FILTER_DIMENSIONS: tuple[str, ...] = (
    "segment",
    "channel",
    "subchannel",
    "amount_tier",
    "status",
    "configuration_id",
    "resolution_method",
)


def normalize_filters(filters: dict[str, list[str]] | None) -> dict[str, list[str]]:
    """Drops empty lists/values; rejects unknown dimension names."""
    normalized: dict[str, list[str]] = {}
    for name, values in (filters or {}).items():
        if name not in FILTER_DIMENSIONS:
            raise ValueError(f"Unknown metrics filter: {name}")
        kept = [str(v).strip() for v in values or [] if str(v).strip()]
        if kept:
            normalized[name] = kept
    return normalized


def snapshot_matches(snapshot: AlertMetricsSnapshot, filters: dict[str, list[str]]) -> bool:
    dims = dict(alert_dimensions(snapshot))
    return all(dims.get(name) in set(values) for name, values in filters.items())

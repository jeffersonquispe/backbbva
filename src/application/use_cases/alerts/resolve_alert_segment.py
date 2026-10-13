from __future__ import annotations

from typing import Any

from src.application.ports.configuration_port import (
    FilterCondition,
    FilterGroup,
    LogicalOperator,
    SegmentSettings,
)
from src.application.ports.tag_catalog_port import TagCategory


def _normalize_rules(rules: Any) -> list[str]:
    # Two known shapes: raw ARIC payload -> list[dict{"name": ...}];
    # CSV/test-run payload -> literal bracketed string, e.g.
    # "[CUSTOMER - Score1000Net]" (see test_pre_process_alert.py).
    if isinstance(rules, list):
        return [
            str(item["name"])
            for item in rules
            if isinstance(item, dict) and item.get("name")
        ]
    if isinstance(rules, str):
        text = rules.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def _alert_values(input_fields: dict[str, Any], roles: dict[str, Any] | None = None) -> dict[TagCategory, list[str]]:
    roles = roles or {}
    if not roles:
        roles = {
            role: input_fields[name]
            for role, name in (("event_type", "event_type"), ("entrypoint", "integration_point"))
            if name in input_fields
        }
    values: dict[TagCategory, list[str]] = {}
    if roles.get("event_type"):
        values[TagCategory.EVENT_TYPE] = [str(roles["event_type"])]
    if roles.get("entrypoint"):
        values[TagCategory.INTEGRATION_POINT] = [str(roles["entrypoint"])]
    rules = _normalize_rules(input_fields.get("rules"))
    if rules:
        values[TagCategory.TRIGGERED_RULE] = rules
    return values


def _condition_matches(
    condition: FilterCondition, alert_values: dict[TagCategory, list[str]]
) -> bool:
    # FilterConditionOperator.IN is the only operator today.
    return bool(set(alert_values.get(condition.category, [])) & set(condition.values))


def _group_matches(
    group: FilterGroup, alert_values: dict[TagCategory, list[str]]
) -> bool:
    results = [_condition_matches(c, alert_values) for c in group.conditions]
    results += [_group_matches(g, alert_values) for g in group.groups]
    if not results:
        return True  # empty group vacuously matches everything.
    return all(results) if group.operator == LogicalOperator.AND else any(results)


class ResolveAlertSegmentUseCase:
    """Which enabled segment's filter matches this alert - pure logic, no
    ports (operates on data the caller already fetched). Tie-break for
    overlapping matches is SegmentSettings.order (admin-editable via
    drag-and-drop on the Segmento tab): an admin who enables a segment
    without narrowing its filter creates a catch-all that wins over any
    segment ordered after it."""

    def execute(
        self,
        input_fields: dict[str, Any],
        segments: dict[str, SegmentSettings],
        roles: dict[str, Any] | None = None,
    ) -> str | None:
        alert_values = _alert_values(input_fields, roles or {})
        ordered = sorted(segments.items(), key=lambda item: item[1].order)
        for code, segment in ordered:
            if not segment.enabled:
                continue
            if _group_matches(segment.filter, alert_values):
                return code
        return None

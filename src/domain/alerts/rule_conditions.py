from __future__ import annotations

from typing import Any

# Mirrors the frontend's RuleConditionEditor COMPARISONS catalog exactly
# (SegmentRubricsSection.tsx, shared by both the Determinístico and
# Rúbricas subtabs) - gt/gte/lt/lte/between are numeric, eq/neq/in do a
# plain string comparison against one or more of `values`.
_NUMERIC_COMPARISONS = {"gt", "gte", "lt", "lte"}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_condition(condition: Any, fields: dict[str, Any]) -> bool:
    """condition is a RuleCondition (or subclass - DeterministicRule) from
    configuration_port.py: {variable, comparison, values}. Not typed as
    RuleCondition directly to dodge an application/ -> domain/ import (see
    CLAUDE.md: domain/ stays framework/port-free) - any object with those
    three attributes works."""
    actual = fields.get(condition.variable)
    values: list[str] = condition.values

    if condition.comparison == "eq":
        return any(str(actual) == v for v in values)
    if condition.comparison == "neq":
        return all(str(actual) != v for v in values)
    if condition.comparison == "in":
        return str(actual) in values
    if condition.comparison == "between":
        if len(values) < 2:
            return False
        low, high = _to_float(values[0]), _to_float(values[1])
        actual_num = _to_float(actual)
        if low is None or high is None or actual_num is None:
            return False
        return low <= actual_num <= high
    if condition.comparison in _NUMERIC_COMPARISONS:
        if not values:
            return False
        target = _to_float(values[0])
        actual_num = _to_float(actual)
        if target is None or actual_num is None:
            return False
        if condition.comparison == "gt":
            return actual_num > target
        if condition.comparison == "gte":
            return actual_num >= target
        if condition.comparison == "lt":
            return actual_num < target
        return actual_num <= target  # lte

    raise ValueError(f"Unsupported RuleCondition.comparison: {condition.comparison!r}")

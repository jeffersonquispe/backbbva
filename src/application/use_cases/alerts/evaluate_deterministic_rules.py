from __future__ import annotations

from typing import Any

from src.application.dtos.evaluate_deterministic_rules_dtos import (
    DeterministicRuleMatch,
)
from src.application.use_cases.alerts.resolve_alert_segment import _alert_values
from src.domain.alerts.rule_conditions import evaluate_condition
from src.domain.configurations.entities import (
    DeterministicRule,
    TagCategory,
)


def _filter_group_matches(
    group: dict[str, Any], alert_values: dict[TagCategory, list[str]]
) -> bool:
    # Twin of resolve_alert_segment.py's _group_matches/_condition_matches,
    # adapted to walk the raw dict shape DeterministicConfig.alert_filter
    # is stored as (it can't be typed as a real FilterGroup at the domain
    # layer - see configuration_port.py's _default_alert_filter comment on
    # declaration order) instead of a parsed FilterGroup/FilterCondition
    # tree. Same semantics: IN-only conditions, empty group vacuously
    # matches everything.
    results = []
    for condition in group.get("conditions") or []:
        try:
            category = TagCategory(condition.get("category"))
        except ValueError:
            results.append(False)
            continue
        values = set(condition.get("values") or [])
        results.append(bool(set(alert_values.get(category, [])) & values))
    for subgroup in group.get("groups") or []:
        results.append(_filter_group_matches(subgroup, alert_values))
    if not results:
        return True
    operator = group.get("operator", "and")
    return all(results) if operator == "and" else any(results)


class EvaluateDeterministicRulesUseCase:
    """Pure logic, no ports (operates on data the caller already fetched) -
    same shape as ResolveAlertSegmentUseCase. `rules` is priority-ordered
    (DeterministicConfig.rules, admin-editable list order): the first rule
    whose condition matches the alert's fields wins, later rules are never
    evaluated. `alert_filter` gates the whole step - an alert that doesn't
    match it skips rule evaluation entirely (independent of the segment's
    own routing filter, which already decided this alert belongs to the
    segment at all)."""

    def execute(
        self,
        rules: list[DeterministicRule],
        fields: dict[str, Any],
        alert_filter: dict[str, Any] | None = None,
    ) -> DeterministicRuleMatch:
        if alert_filter and not _filter_group_matches(
            alert_filter, _alert_values(fields)
        ):
            return DeterministicRuleMatch(matched=False)
        for rule in rules:
            if evaluate_condition(rule, fields):
                return DeterministicRuleMatch(
                    matched=True,
                    rule_id=rule.id,
                    variable=rule.variable,
                    decision=rule.decision,
                    aric_action=rule.aric_action,
                )
        return DeterministicRuleMatch(matched=False)

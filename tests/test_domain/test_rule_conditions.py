from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.domain.alerts.rule_conditions import evaluate_condition


@dataclass
class _Condition:
    variable: str = ""
    comparison: str = "eq"
    values: list[str] = field(default_factory=list)


def test_eq_matches_any_of_the_values() -> None:
    cond = _Condition(variable="channel", comparison="eq", values=["web", "app"])
    assert evaluate_condition(cond, {"channel": "app"}) is True
    assert evaluate_condition(cond, {"channel": "atm"}) is False


def test_neq_requires_none_of_the_values_to_match() -> None:
    cond = _Condition(variable="channel", comparison="neq", values=["web"])
    assert evaluate_condition(cond, {"channel": "app"}) is True
    assert evaluate_condition(cond, {"channel": "web"}) is False


def test_in_checks_plain_membership() -> None:
    cond = _Condition(variable="channel", comparison="in", values=["web", "app", "atm"])
    assert evaluate_condition(cond, {"channel": "atm"}) is True
    assert evaluate_condition(cond, {"channel": "branch"}) is False


@pytest.mark.parametrize(
    "comparison, amount, expected",
    [
        ("gt", 3001, True),
        ("gt", 3000, False),
        ("gte", 3000, True),
        ("lt", 2999, True),
        ("lt", 3000, False),
        ("lte", 3000, True),
    ],
)
def test_numeric_comparisons(comparison: str, amount: int, expected: bool) -> None:
    cond = _Condition(variable="amount", comparison=comparison, values=["3000"])
    assert evaluate_condition(cond, {"amount": amount}) is expected


def test_between_checks_inclusive_range() -> None:
    cond = _Condition(variable="amount", comparison="between", values=["100", "200"])
    assert evaluate_condition(cond, {"amount": 100}) is True
    assert evaluate_condition(cond, {"amount": 200}) is True
    assert evaluate_condition(cond, {"amount": 201}) is False


def test_numeric_comparison_with_non_numeric_field_is_false_not_an_error() -> None:
    cond = _Condition(variable="amount", comparison="gt", values=["3000"])
    assert evaluate_condition(cond, {"amount": "not-a-number"}) is False
    assert evaluate_condition(cond, {}) is False


def test_unsupported_comparison_raises() -> None:
    cond = _Condition(variable="amount", comparison="regex", values=["^A"])
    with pytest.raises(ValueError, match="Unsupported"):
        evaluate_condition(cond, {"amount": "ABC"})

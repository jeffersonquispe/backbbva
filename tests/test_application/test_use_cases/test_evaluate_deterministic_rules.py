from __future__ import annotations

from src.application.ports.configuration_port import DeterministicRule
from src.application.use_cases.alerts.evaluate_deterministic_rules import (
    EvaluateDeterministicRulesUseCase,
)


def test_no_rules_never_matches() -> None:
    use_case = EvaluateDeterministicRulesUseCase()

    result = use_case.execute([], {"amount": 5000})

    assert result.matched is False
    assert result.rule_id is None


def test_first_matching_rule_wins_by_list_order() -> None:
    rules = [
        DeterministicRule(
            id="r1",
            variable="amount",
            comparison="gt",
            values=["10000"],
            decision="risk",
            aric_action="hard_block",
        ),
        DeterministicRule(
            id="r2",
            variable="amount",
            comparison="gt",
            values=["1000"],
            decision="risk_suspected",
            aric_action="soft_block",
        ),
    ]
    use_case = EvaluateDeterministicRulesUseCase()

    result = use_case.execute(rules, {"amount": 5000})

    assert result.matched is True
    assert result.rule_id == "r2"
    assert result.decision == "risk_suspected"
    assert result.aric_action == "soft_block"


def test_no_rule_matches_returns_unmatched() -> None:
    rules = [
        DeterministicRule(
            id="r1",
            variable="amount",
            comparison="gt",
            values=["10000"],
            decision="risk",
            aric_action="hard_block",
        )
    ]
    use_case = EvaluateDeterministicRulesUseCase()

    result = use_case.execute(rules, {"amount": 500})

    assert result.matched is False


def test_alert_filter_gates_the_whole_step() -> None:
    rules = [
        DeterministicRule(
            id="r1",
            variable="amount",
            comparison="gt",
            values=["100"],
            decision="risk",
            aric_action="hard_block",
        )
    ]
    alert_filter = {
        "id": "root",
        "operator": "and",
        "conditions": [
            {"id": "c1", "category": "integration_point", "values": ["APP"]}
        ],
        "groups": [],
    }
    use_case = EvaluateDeterministicRulesUseCase()

    # Rule would match on amount alone, but the filter excludes this
    # integration_point.
    result = use_case.execute(
        rules,
        {"amount": 5000, "integration_point": "WEB"},
        alert_filter=alert_filter,
    )
    assert result.matched is False

    result = use_case.execute(
        rules,
        {"amount": 5000, "integration_point": "APP"},
        alert_filter=alert_filter,
    )
    assert result.matched is True


def test_empty_alert_filter_matches_everything() -> None:
    rules = [
        DeterministicRule(
            id="r1",
            variable="amount",
            comparison="gt",
            values=["100"],
            decision="risk",
            aric_action="hard_block",
        )
    ]
    empty_filter = {"id": "root", "operator": "and", "conditions": [], "groups": []}
    use_case = EvaluateDeterministicRulesUseCase()

    result = use_case.execute(rules, {"amount": 5000}, alert_filter=empty_filter)

    assert result.matched is True

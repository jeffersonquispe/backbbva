from hypothesis import given
from hypothesis import strategies as st

from src.domain.alerts.rule_conditions import evaluate_condition
from src.domain.configurations.entities import RuleCondition


@given(actual=st.integers(), target=st.integers())
def test_numeric_comparisons_match_integer_ordering(actual: int, target: int) -> None:
    fields = {"amount": actual}
    expected = {
        "gt": actual > target,
        "gte": actual >= target,
        "lt": actual < target,
        "lte": actual <= target,
    }

    for comparison, result in expected.items():
        condition = RuleCondition(
            variable="amount", comparison=comparison, values=[str(target)]
        )
        assert evaluate_condition(condition, fields) is result


@given(
    lower=st.integers(),
    upper=st.integers(),
    actual=st.integers(),
)
def test_between_is_inclusive_and_rejects_reversed_bounds(
    lower: int, upper: int, actual: int
) -> None:
    condition = RuleCondition(
        variable="amount", comparison="between", values=[str(lower), str(upper)]
    )

    assert evaluate_condition(condition, {"amount": actual}) is (
        lower <= actual <= upper
    )

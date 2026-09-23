from __future__ import annotations

import pytest

from src.domain.alerts.calculator import CalculatorError, safe_calculate


def test_evaluates_basic_arithmetic() -> None:
    assert safe_calculate("2 + 3 * 4") == 14
    assert safe_calculate("(2 + 3) * 4") == 20
    assert safe_calculate("10 / 4") == 2.5
    assert safe_calculate("2 ** 10") == 1024
    assert safe_calculate("-5 + 2") == -3


def test_rejects_division_by_zero() -> None:
    with pytest.raises(CalculatorError):
        safe_calculate("1 / 0")


def test_rejects_names_and_calls() -> None:
    with pytest.raises(CalculatorError):
        safe_calculate("__import__('os').system('echo hi')")
    with pytest.raises(CalculatorError):
        safe_calculate("open('/etc/passwd')")
    with pytest.raises(CalculatorError):
        safe_calculate("some_variable + 1")


def test_rejects_unparseable_expression() -> None:
    with pytest.raises(CalculatorError):
        safe_calculate("this is not math")
    with pytest.raises(CalculatorError):
        safe_calculate("")

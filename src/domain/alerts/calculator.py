from __future__ import annotations

import ast
import operator
from collections.abc import Callable

# Pure arithmetic evaluator for the "calculator" tool switch (Classification
# /Adversarial ClassificationConfig.calculator_enabled): lets an LLM agent
# ask for an exact numeric result (e.g. a ratio or a sum over amounts it
# already has) instead of estimating it in prose. Framework-free by design
# (domain/ - see CLAUDE.md), and deliberately NOT a bare eval() of the
# model's output - only a whitelisted subset of ast node types is walked,
# so the agent can't smuggle arbitrary code through the tool.

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorError(ValueError):
    """The expression isn't a supported arithmetic expression."""


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise CalculatorError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        try:
            return _BINARY_OPERATORS[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise CalculatorError("Division by zero") from exc
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_eval_node(node.operand))
    raise CalculatorError(f"Unsupported expression: {ast.dump(node)}")


def safe_calculate(expression: str) -> float:
    """Evaluates a plain arithmetic expression (+ - * / // % ** and
    parentheses, no names/calls/attributes) and returns the numeric
    result. Raises CalculatorError on anything else, including a blank or
    unparseable expression - callers (the ReAct tool wrapper) turn that
    into an Observation the agent can read and retry from, not a crash."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"Could not parse expression: {expression!r}") from exc
    return _eval_node(tree.body)

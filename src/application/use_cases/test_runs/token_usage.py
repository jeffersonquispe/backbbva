from __future__ import annotations

from src.domain.workflows.entities import (
    WorkflowStepExecutionRecord,
)


def sum_step_tokens(
    steps: list[WorkflowStepExecutionRecord],
) -> tuple[int, int]:
    """(input_tokens, output_tokens) summed across every step attempt.

    Non-LLM steps (pre_process, executor, post_process) simply have no
    input_tokens/output_tokens keys in their output dict and contribute 0 -
    no need to special-case them here.
    """
    input_tokens = 0
    output_tokens = 0
    for step in steps:
        output = step.output or {}
        input_tokens += output.get("input_tokens") or 0
        output_tokens += output.get("output_tokens") or 0
    return input_tokens, output_tokens

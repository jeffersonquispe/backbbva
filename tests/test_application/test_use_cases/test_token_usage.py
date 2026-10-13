from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.use_cases.test_runs.token_usage import sum_step_tokens
from src.domain.workflows.entities import (
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)


def _step(output: dict | None) -> WorkflowStepExecutionRecord:
    now = datetime.now(UTC)
    return WorkflowStepExecutionRecord(
        id=uuid.uuid4(),
        workflow_execution_id=uuid.uuid4(),
        step_name="classification",
        status=WorkflowStepStatus.SUCCEEDED,
        attempt=1,
        input={},
        output=output,
        error=None,
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


def test_sums_across_llm_backed_steps() -> None:
    steps = [
        _step({"input_tokens": 100, "output_tokens": 20}),
        _step({"input_tokens": 50, "output_tokens": 10}),
    ]

    assert sum_step_tokens(steps) == (150, 30)


def test_non_llm_steps_contribute_zero() -> None:
    steps = [
        _step({"input_tokens": 100, "output_tokens": 20}),
        _step({"executed_action": "none"}),  # e.g. executor's output
        _step(None),  # e.g. pre_process with a bare dataclass-asdict output
    ]

    assert sum_step_tokens(steps) == (100, 20)


def test_empty_list_returns_zero() -> None:
    assert sum_step_tokens([]) == (0, 0)

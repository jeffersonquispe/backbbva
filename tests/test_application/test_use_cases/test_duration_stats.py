from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from src.application.use_cases.test_runs.duration_stats import (
    compute_stats,
    step_duration_stats_by_name,
    workflow_duration,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)


def _step(
    step_name: str, duration_seconds: float | None
) -> WorkflowStepExecutionRecord:
    now = datetime.now(UTC)
    finished = (
        now + timedelta(seconds=duration_seconds)
        if duration_seconds is not None
        else None
    )
    return WorkflowStepExecutionRecord(
        id=uuid.uuid4(),
        workflow_execution_id=uuid.uuid4(),
        step_name=step_name,
        status=WorkflowStepStatus.SUCCEEDED,
        attempt=1,
        input={},
        output={},
        error=None,
        started_at=now,
        finished_at=finished,
        created_at=now,
        updated_at=now,
    )


def test_compute_stats_returns_none_for_empty_input() -> None:
    assert compute_stats([]) is None


def test_compute_stats_min_max_avg_p95() -> None:
    stats = compute_stats([1.0, 2.0, 3.0, 4.0, 100.0])

    assert stats is not None
    assert stats.count == 5
    assert stats.min_seconds == 1.0
    assert stats.max_seconds == 100.0
    assert stats.avg_seconds == 22.0
    # Nearest-rank p95 of 5 sorted values -> index ceil(0.95*5)-1 = 4 (last).
    assert stats.p95_seconds == 100.0


def test_step_duration_stats_by_name_groups_by_stage_and_skips_unfinished() -> None:
    steps = [
        _step("classification", 2.0),
        _step("classification", 4.0),
        _step("profiling", 1.0),
        _step("classification", None),  # still running - no finished_at yet
    ]

    stats = step_duration_stats_by_name(steps)

    assert set(stats) == {"classification", "profiling"}
    assert stats["classification"].count == 2
    assert stats["classification"].avg_seconds == 3.0
    assert stats["profiling"].count == 1


def test_workflow_duration_none_when_not_finished() -> None:
    now = datetime.now(UTC)
    workflow = WorkflowExecutionRecord(
        id=uuid.uuid4(),
        alert_id=uuid.uuid4(),
        async_operation_id=uuid.uuid4(),
        workflow_name="massive_fraud_alert_review",
        status=WorkflowStatus.RUNNING,
        input={},
        output=None,
        error=None,
        current_step=None,
        feedback_iterations=0,
        max_feedback_iterations=2,
        created_at=now,
        updated_at=now,
    )

    assert workflow_duration(workflow) is None

    workflow.finished_at = now + timedelta(seconds=12.5)
    assert workflow_duration(workflow) == 12.5

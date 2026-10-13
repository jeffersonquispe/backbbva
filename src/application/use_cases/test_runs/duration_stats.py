from __future__ import annotations

from math import ceil

from src.application.dtos.test_run_dtos import DurationStats
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStepExecutionRecord,
)


def compute_stats(durations: list[float]) -> DurationStats | None:
    if not durations:
        return None
    ordered = sorted(durations)
    # Nearest-rank percentile - no interpolation needed for run-sized
    # samples (tens to low hundreds of cases).
    p95_index = max(0, ceil(0.95 * len(ordered)) - 1)
    return DurationStats(
        count=len(ordered),
        min_seconds=ordered[0],
        max_seconds=ordered[-1],
        avg_seconds=sum(ordered) / len(ordered),
        p95_seconds=ordered[p95_index],
    )


def step_duration_stats_by_name(
    steps: list[WorkflowStepExecutionRecord],
) -> dict[str, DurationStats]:
    """Per-stage worker duration stats (perc95/avg/min/max), across every
    attempt of every case's step in a test run."""
    by_name: dict[str, list[float]] = {}
    for step in steps:
        if step.started_at is None or step.finished_at is None:
            continue
        by_name.setdefault(step.step_name, []).append(
            (step.finished_at - step.started_at).total_seconds()
        )
    stats_by_name: dict[str, DurationStats] = {}
    for name, durations in by_name.items():
        stats = compute_stats(durations)
        if stats is not None:
            stats_by_name[name] = stats
    return stats_by_name


def workflow_duration(workflow: WorkflowExecutionRecord) -> float | None:
    if workflow.finished_at is None:
        return None
    return (workflow.finished_at - workflow.created_at).total_seconds()

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.application.ports.test_run_port import TestRunConfig, TestRunStatus
from src.application.ports.workflow_port import WorkflowStatus


@dataclass
class StartTestRunInput:
    name: str
    dataset_name: str
    config: TestRunConfig = field(default_factory=TestRunConfig)
    # None (both) = dispatch every row, unchanged default behavior.
    # sample_size alone = stratify by the dataset's own observed
    # no-risk/risk-suspected/risk proportions. Both = stratify by the
    # given proportions instead (e.g. a class-balanced sample). See
    # dataset_sampling.sample_rows for exact semantics.
    sample_size: int | None = None
    sample_distribution: dict[str, float] | None = None


@dataclass
class StartTestRunOutput:
    test_run_id: UUID
    dispatched_count: int


@dataclass
class DurationStats:
    """perc95/avg/min/max over a set of worker durations (seconds) - see
    duration_stats.py for how these get computed, recomputed fresh on
    every read from started_at/finished_at rather than stored."""

    count: int
    min_seconds: float
    max_seconds: float
    avg_seconds: float
    p95_seconds: float


@dataclass
class ClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class ClassificationMetrics:
    """One confusion matrix + per-class precision/recall/f1 - see
    classification_metrics.py for how these get computed. Two independent
    instances of this live on TestRunDetail: one scoring the model against
    the analyst's marcacion_final, one against the real matured outcome
    (tipo) - see that module for the two label mappings."""

    per_class: dict[str, ClassMetrics]
    macro_precision: float
    macro_recall: float
    macro_f1: float
    # expected label -> predicted label -> count.
    confusion_matrix: dict[str, dict[str, int]]
    total: int


@dataclass
class TestCaseSummary:
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    current_step: str | None
    duration_seconds: float | None = None


@dataclass
class TestRunDetail:
    id: UUID
    name: str
    dataset_name: str
    config: TestRunConfig
    status: TestRunStatus
    total: int
    succeeded: int
    failed: int
    running: int
    pending: int
    # Consolidated across every case and every LLM-backed step attempt in
    # this run - see token_usage.sum_step_tokens. Non-LLM steps
    # contribute 0, nothing to subtract for them.
    input_tokens: int
    output_tokens: int
    cases: list[TestCaseSummary]
    # Worker duration stats per pipeline stage (LINEAR_STEPS name -> stats
    # across every attempt of that stage in this run), plus one overall
    # stats block across each case's total (created_at -> finished_at)
    # duration. See duration_stats.py.
    step_duration_stats: dict[str, DurationStats] = field(default_factory=dict)
    total_duration_stats: DurationStats | None = None
    # See classification_metrics.py - computed from each case's final
    # classification attempt, None until at least one case has one.
    analyst_agreement_metrics: ClassificationMetrics | None = None
    ground_truth_metrics: ClassificationMetrics | None = None


@dataclass
class DeleteTestRunsInput:
    test_run_ids: list[UUID]


@dataclass
class DeleteTestRunsOutput:
    deleted_test_runs: int
    deleted_cases: int

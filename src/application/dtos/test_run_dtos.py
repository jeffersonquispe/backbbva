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
class TestCaseSummary:
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    current_step: str | None


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

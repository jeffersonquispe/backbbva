from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.domain.test_runs.entities import TestRunStatus
from src.domain.workflows.entities import (
    WorkflowStatus,
    WorkflowStepStatus,
)


class ConfigurationRefRequest(BaseModel):
    configuration_id: str
    # None = that lineage's latest version.
    version: int | None = None


class TestRunConfigRequest(BaseModel):
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    # How many classification<->adversarial feedback loops a case gets
    # before escalating to an analyst - see WorkflowExecutionRecord.
    # max_feedback_iterations.
    max_feedback_iterations: int = Field(default=1, ge=0)
    # Pin this test run to one specific (possibly inactive)
    # ConfigurationRecord instead of the currently-active one - lets
    # multiple test runs each target a different configuration
    # concurrently without touching the global active flag.
    configuration_ref: ConfigurationRefRequest | None = None
    schema_version: int | None = Field(default=None, ge=1)
    active_schema_version: int | None = Field(default=None, ge=1)


class StartTestRunRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    dataset_name: str = Field(..., min_length=1)
    config: TestRunConfigRequest = Field(default_factory=TestRunConfigRequest)
    # Both unset = dispatch every row (unchanged default). sample_size
    # alone = stratify by the dataset's own no-risk/risk-suspected/risk
    # proportions. Both set = stratify by these exact proportions instead
    # (e.g. a class-balanced sample). Keys must be "no-risk",
    # "risk-suspected", "risk", summing to 1.0.
    sample_size: int | None = Field(default=None, gt=0)
    sample_distribution: dict[str, float] | None = None


class StartTestRunResponse(BaseModel):
    test_run_id: UUID
    dispatched_count: int


class TestRunResponse(BaseModel):
    id: UUID
    name: str
    dataset_name: str
    status: TestRunStatus
    total: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    # Nested (not a flattened configuration_ref field) so this matches the
    # same test_run.config -> TestRunConfigRequest attribute pass-through
    # TestRunDetailResponse already relies on below - configuration_ref is
    # None when this run tested the active configuration at dispatch time
    # (today's only behavior before ConfigurationRef existed). See
    # TestRunConfig.configuration_ref (domain/test_runs/entities.py).
    config: TestRunConfigRequest


class TestCaseSummaryResponse(BaseModel):
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    current_step: str | None
    duration_seconds: float | None


class DurationStatsResponse(BaseModel):
    count: int
    min_seconds: float
    max_seconds: float
    avg_seconds: float
    p95_seconds: float


class ClassMetricsResponse(BaseModel):
    precision: float
    recall: float
    f1: float
    support: int


class ClassificationMetricsResponse(BaseModel):
    per_class: dict[str, ClassMetricsResponse]
    macro_precision: float
    macro_recall: float
    macro_f1: float
    confusion_matrix: dict[str, dict[str, int]]
    total: int


class TestRunDetailResponse(BaseModel):
    id: UUID
    name: str
    dataset_name: str
    config: TestRunConfigRequest
    status: TestRunStatus
    total: int
    succeeded: int
    failed: int
    running: int
    pending: int
    input_tokens: int
    output_tokens: int
    cases: list[TestCaseSummaryResponse]
    step_duration_stats: dict[str, DurationStatsResponse]
    total_duration_stats: DurationStatsResponse | None
    analyst_agreement_metrics: ClassificationMetricsResponse | None
    ground_truth_metrics: ClassificationMetricsResponse | None


class WorkflowStepResponse(BaseModel):
    id: UUID
    step_name: str
    status: WorkflowStepStatus
    attempt: int
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class TestCaseDetailResponse(BaseModel):
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    input_tokens: int
    output_tokens: int
    steps: list[WorkflowStepResponse]
    schema_comparison: dict[str, Any] | None = None
    schema_version: int | None = None
    configuration_ref: dict[str, Any] | None = None


class DeleteTestRunsRequest(BaseModel):
    test_run_ids: list[UUID] = Field(..., min_length=1)


class DeleteTestRunsResponse(BaseModel):
    deleted_test_runs: int
    deleted_cases: int

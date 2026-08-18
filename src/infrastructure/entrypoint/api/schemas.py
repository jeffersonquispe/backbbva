from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.ports.async_execution_inspector_port import (
    AsyncExecutionState,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.test_run_port import TestRunStatus
from src.application.ports.workflow_port import WorkflowStatus, WorkflowStepStatus


class CreateAsyncOperationRequest(BaseModel):
    operation_type: str = Field(..., min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=120)


class UpdateAsyncOperationRequest(BaseModel):
    status: AsyncOperationStatus | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class AsyncOperationResponse(BaseModel):
    id: UUID
    operation_type: str
    status: AsyncOperationStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    dispatched_at: datetime | None
    execution_backend: str | None
    external_id: str | None


class AsyncOperationPollingResponse(BaseModel):
    id: UUID
    status: AsyncOperationStatus
    done: bool
    retry_after_seconds: int | None
    result: dict[str, Any] | None
    error: str | None
    updated_at: datetime


class ReconcileAsyncOperationsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class ReconciledAsyncOperationResponse(BaseModel):
    id: UUID
    previous_status: AsyncOperationStatus
    current_status: AsyncOperationStatus
    execution_state: AsyncExecutionState
    detail: str | None


class ReconcileAsyncOperationsResponse(BaseModel):
    inspected: int
    updated: int
    operations: list[ReconciledAsyncOperationResponse]


class TestRunConfigRequest(BaseModel):
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    model_overrides: dict[str, str] = Field(default_factory=dict)


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


class TestCaseSummaryResponse(BaseModel):
    workflow_execution_id: UUID
    alert_id: UUID
    status: WorkflowStatus
    current_step: str | None


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


class DatasetResponse(BaseModel):
    name: str
    row_count: int

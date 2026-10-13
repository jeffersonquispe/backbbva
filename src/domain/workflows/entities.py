from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class WorkflowStatus(StrEnum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class WorkflowStepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass
class WorkflowExecutionRecord:
    id: UUID
    alert_id: UUID
    async_operation_id: UUID
    workflow_name: str
    status: WorkflowStatus
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    current_step: str | None
    feedback_iterations: int
    max_feedback_iterations: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    execution_backend: str | None = None
    external_id: str | None = None
    test_run_id: UUID | None = None
    schema_comparison: dict[str, Any] | None = None


@dataclass
class WorkflowStepExecutionRecord:
    id: UUID
    workflow_execution_id: UUID
    step_name: str
    status: WorkflowStepStatus
    attempt: int
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

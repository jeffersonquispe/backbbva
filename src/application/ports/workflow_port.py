from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
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


class WorkflowExecutionRepository(Protocol):
    def create(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRecord:
        ...

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        ...

    def update(
        self,
        workflow_id: UUID,
        *,
        status: WorkflowStatus | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        current_step: str | None = None,
        feedback_iterations: int | None = None,
        finished_at: datetime | None = None,
        execution_backend: str | None = None,
        external_id: str | None = None,
    ) -> WorkflowExecutionRecord | None:
        ...


class WorkflowStepExecutionRepository(Protocol):
    def create(
        self,
        step: WorkflowStepExecutionRecord,
    ) -> WorkflowStepExecutionRecord:
        ...

    def list_by_workflow(
        self,
        workflow_execution_id: UUID,
    ) -> list[WorkflowStepExecutionRecord]:
        ...

    def update(
        self,
        workflow_execution_id: UUID,
        step_id: UUID,
        *,
        status: WorkflowStepStatus | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> WorkflowStepExecutionRecord | None:
        ...

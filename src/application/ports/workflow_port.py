from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)


class WorkflowExecutionRepository(Protocol):
    def create(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRecord: ...

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None: ...

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
        schema_comparison: dict[str, Any] | None = None,
    ) -> WorkflowExecutionRecord | None: ...

    def list_by_test_run(
        self,
        test_run_id: UUID,
    ) -> list[WorkflowExecutionRecord]: ...

    def delete(self, workflow_id: UUID) -> None: ...


class WorkflowStepExecutionRepository(Protocol):
    def create(
        self,
        step: WorkflowStepExecutionRecord,
    ) -> WorkflowStepExecutionRecord: ...

    def list_by_workflow(
        self,
        workflow_execution_id: UUID,
    ) -> list[WorkflowStepExecutionRecord]: ...

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
    ) -> WorkflowStepExecutionRecord | None: ...

    def delete(self, workflow_execution_id: UUID, step_id: UUID) -> None: ...

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from src.domain.workflows.entities import (
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)


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

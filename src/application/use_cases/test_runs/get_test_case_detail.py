from __future__ import annotations

from uuid import UUID

from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStepExecutionRepository,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStepExecutionRecord,
)


class GetTestCaseDetailUseCase:
    def __init__(
        self,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
    ) -> None:
        self._workflows = workflow_repository
        self._steps = step_repository

    def execute(
        self, workflow_execution_id: UUID
    ) -> tuple[WorkflowExecutionRecord, list[WorkflowStepExecutionRecord]] | None:
        workflow = self._workflows.get(workflow_execution_id)
        if workflow is None:
            return None
        # input/output per step already carries cot/input_tokens/output_tokens
        # for the LLM-backed steps (see classify_alert.py etc.) - nothing
        # extra to assemble here, this is the dashboard's per-agent view.
        return workflow, self._steps.list_by_workflow(workflow_execution_id)

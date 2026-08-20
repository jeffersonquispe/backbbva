from __future__ import annotations

from src.application.dtos.test_run_dtos import DeleteTestRunsInput, DeleteTestRunsOutput
from src.application.ports.alert_port import AlertRepository
from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.ports.test_run_port import TestRunRepository
from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStepExecutionRepository,
)


class DeleteTestRunsUseCase:
    """Cascade-deletes one or more test runs: every case they dispatched
    (workflow execution + its step attempts, plus the alert and
    async-operation that case created - see start_alert_test_workflow.py),
    then the test run record itself. Children deleted before parents, and
    delete_item is idempotent, so a partial retry after a mid-batch failure
    is safe."""

    def __init__(
        self,
        test_run_repository: TestRunRepository,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
        alert_repository: AlertRepository,
        async_operation_repository: AsyncOperationRepository,
    ) -> None:
        self._test_runs = test_run_repository
        self._workflows = workflow_repository
        self._steps = step_repository
        self._alerts = alert_repository
        self._operations = async_operation_repository

    def execute(self, input: DeleteTestRunsInput) -> DeleteTestRunsOutput:
        deleted_cases = 0
        for test_run_id in input.test_run_ids:
            for workflow in self._workflows.list_by_test_run(test_run_id):
                for step in self._steps.list_by_workflow(workflow.id):
                    self._steps.delete(workflow.id, step.id)
                self._alerts.delete(workflow.alert_id)
                self._operations.delete(workflow.async_operation_id)
                self._workflows.delete(workflow.id)
                deleted_cases += 1
            self._test_runs.delete(test_run_id)
        return DeleteTestRunsOutput(
            deleted_test_runs=len(input.test_run_ids),
            deleted_cases=deleted_cases,
        )

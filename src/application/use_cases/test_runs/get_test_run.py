from __future__ import annotations

from uuid import UUID

from src.application.dtos.test_run_dtos import TestCaseSummary, TestRunDetail
from src.application.ports.test_run_port import TestRunRepository, TestRunStatus
from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStatus,
    WorkflowStepExecutionRepository,
)
from src.application.use_cases.test_runs.token_usage import sum_step_tokens

_FAILED = {WorkflowStatus.FAILED}
_RUNNING = {WorkflowStatus.RUNNING, WorkflowStatus.DISPATCHED}
_PENDING = {WorkflowStatus.PENDING}


def derive_test_run_status(
    *, total: int, succeeded: int, failed: int, running: int, pending: int
) -> TestRunStatus:
    # TestRunRecord.status is written once (PENDING -> RUNNING) at dispatch
    # and never updated again - nothing observes individual case
    # completions to roll it up. Recompute it from live case counts on
    # every read instead of trusting the stored field, so a finished run
    # doesn't show RUNNING forever.
    if running or pending:
        return TestRunStatus.RUNNING
    if total == 0:
        return TestRunStatus.RUNNING
    return TestRunStatus.FAILED if failed else TestRunStatus.SUCCEEDED


class GetTestRunUseCase:
    def __init__(
        self,
        test_run_repository: TestRunRepository,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
    ) -> None:
        self._test_runs = test_run_repository
        self._workflows = workflow_repository
        self._steps = step_repository

    def execute(self, test_run_id: UUID) -> TestRunDetail | None:
        test_run = self._test_runs.get(test_run_id)
        if test_run is None:
            return None

        workflows = self._workflows.list_by_test_run(test_run_id)
        succeeded = sum(
            1 for w in workflows if w.status == WorkflowStatus.SUCCEEDED
        )
        failed = sum(1 for w in workflows if w.status in _FAILED)
        running = sum(1 for w in workflows if w.status in _RUNNING)
        pending = sum(1 for w in workflows if w.status in _PENDING)

        status = derive_test_run_status(
            total=test_run.total,
            succeeded=succeeded,
            failed=failed,
            running=running,
            pending=pending,
        )

        input_tokens = 0
        output_tokens = 0
        for w in workflows:
            step_input, step_output = sum_step_tokens(
                self._steps.list_by_workflow(w.id)
            )
            input_tokens += step_input
            output_tokens += step_output

        return TestRunDetail(
            id=test_run.id,
            name=test_run.name,
            dataset_name=test_run.dataset_name,
            config=test_run.config,
            status=status,
            total=test_run.total,
            succeeded=succeeded,
            failed=failed,
            running=running,
            pending=pending,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cases=[
                TestCaseSummary(
                    workflow_execution_id=w.id,
                    alert_id=w.alert_id,
                    status=w.status,
                    current_step=w.current_step,
                )
                for w in workflows
            ],
        )

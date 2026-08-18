from __future__ import annotations

import dataclasses

from src.application.ports.test_run_port import TestRunRecord, TestRunRepository
from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStatus,
)
from src.application.use_cases.test_runs.get_test_run import (
    _FAILED,
    _PENDING,
    _RUNNING,
    derive_test_run_status,
)


class ListTestRunsUseCase:
    def __init__(
        self,
        test_run_repository: TestRunRepository,
        workflow_repository: WorkflowExecutionRepository,
    ) -> None:
        self._test_runs = test_run_repository
        self._workflows = workflow_repository

    def execute(self) -> list[TestRunRecord]:
        return [self._with_derived_status(run) for run in self._test_runs.list()]

    def _with_derived_status(self, run: TestRunRecord) -> TestRunRecord:
        workflows = self._workflows.list_by_test_run(run.id)
        status = derive_test_run_status(
            total=run.total,
            succeeded=sum(1 for w in workflows if w.status == WorkflowStatus.SUCCEEDED),
            failed=sum(1 for w in workflows if w.status in _FAILED),
            running=sum(1 for w in workflows if w.status in _RUNNING),
            pending=sum(1 for w in workflows if w.status in _PENDING),
        )
        return dataclasses.replace(run, status=status)

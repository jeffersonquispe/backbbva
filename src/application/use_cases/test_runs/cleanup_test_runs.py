from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.configuration_port import TestCleanupPolicy
from src.application.ports.test_run_port import TestRunStatus
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsUseCase
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase


@dataclass(frozen=True)
class CleanupTestRunsOutput:
    deleted_test_runs: int
    deleted_cases: int
    deferred_active_runs: int


class CleanupTestRunsUseCase:
    """Apply the configured retention cap without ever deleting active work."""

    def __init__(
        self,
        list_test_runs: ListTestRunsUseCase,
        delete_test_runs: DeleteTestRunsUseCase,
    ) -> None:
        self._list = list_test_runs
        self._delete = delete_test_runs

    def execute(
        self, max_stored_test_runs: int, policy: TestCleanupPolicy
    ) -> CleanupTestRunsOutput:
        runs = self._list.execute(order="desc")
        excess = max(0, len(runs) - max_stored_test_runs)
        if policy == TestCleanupPolicy.MANUAL or excess == 0:
            return CleanupTestRunsOutput(0, 0, excess)

        terminal = [
            run
            for run in runs
            if run.status in {TestRunStatus.SUCCEEDED, TestRunStatus.FAILED}
        ]
        if policy == TestCleanupPolicy.FAILED_FIRST:
            terminal.sort(
                key=lambda run: (run.status != TestRunStatus.FAILED, run.created_at)
            )
        else:  # OLDEST
            terminal.sort(key=lambda run: run.created_at)

        selected: list[UUID] = [run.id for run in terminal[:excess]]
        if not selected:
            return CleanupTestRunsOutput(0, 0, excess)
        deleted = self._delete.execute_for_ids(selected)
        return CleanupTestRunsOutput(
            deleted.deleted_test_runs,
            deleted.deleted_cases,
            excess - len(selected),
        )

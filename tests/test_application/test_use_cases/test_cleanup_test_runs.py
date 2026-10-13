from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.application.ports.test_run_port import (
    TestRunConfig as RunConfig,
)
from src.application.ports.test_run_port import (
    TestRunRecord as RunRecord,
)
from src.application.ports.test_run_port import (
    TestRunStatus as RunStatus,
)
from src.application.use_cases.test_runs.cleanup_test_runs import CleanupTestRunsUseCase
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsOutput
from src.domain.configurations.entities import (
    TestCleanupPolicy as CleanupPolicy,
)


class StaticListTestRuns:
    def __init__(self, runs):
        self.runs = runs

    def execute(self, order="desc"):
        return self.runs


class RecordingDeleteTestRuns:
    def __init__(self):
        self.ids = []

    def execute_for_ids(self, ids):
        self.ids = ids
        return DeleteTestRunsOutput(
            deleted_test_runs=len(ids), deleted_cases=len(ids) * 2
        )


def _run(status, age_hours):
    now = datetime.now(UTC)
    return RunRecord(
        id=uuid4(),
        name="run",
        dataset_name="dataset",
        config=RunConfig(),
        status=status,
        total=1,
        created_at=now - timedelta(hours=age_hours),
        updated_at=now,
    )


def test_failed_first_preserves_active_runs_and_removes_failed_first():
    failed = _run(RunStatus.FAILED, 1)
    succeeded = _run(RunStatus.SUCCEEDED, 10)
    running = _run(RunStatus.RUNNING, 2)
    delete = RecordingDeleteTestRuns()
    use_case = CleanupTestRunsUseCase(
        StaticListTestRuns([failed, succeeded, running]), delete
    )

    output = use_case.execute(2, CleanupPolicy.FAILED_FIRST)

    assert delete.ids == [failed.id]
    assert output.deleted_test_runs == 1
    assert output.deleted_cases == 2


def test_manual_policy_never_deletes_runs():
    delete = RecordingDeleteTestRuns()
    use_case = CleanupTestRunsUseCase(
        StaticListTestRuns([_run(RunStatus.SUCCEEDED, 1), _run(RunStatus.FAILED, 2)]),
        delete,
    )

    output = use_case.execute(1, CleanupPolicy.MANUAL)

    assert delete.ids == []
    assert output.deleted_test_runs == 0

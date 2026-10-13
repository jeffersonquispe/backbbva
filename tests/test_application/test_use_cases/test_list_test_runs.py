from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.application.ports.test_run_port import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
)


class InMemoryTestRunRepository:
    def __init__(self, runs: list[TestRunRecord]) -> None:
        self._runs = runs

    def create(self, run):
        raise NotImplementedError

    def get(self, run_id):
        raise NotImplementedError

    def update(self, run_id, **changes):
        raise NotImplementedError

    def list(self) -> list[TestRunRecord]:
        return list(self._runs)


class InMemoryWorkflowExecutionRepository:
    def create(self, workflow):
        raise NotImplementedError

    def get(self, workflow_id):
        raise NotImplementedError

    def update(self, workflow_id, **changes):
        raise NotImplementedError

    def list_by_test_run(self, test_run_id: UUID) -> list[WorkflowExecutionRecord]:
        return []


def _run(created_at: datetime) -> TestRunRecord:
    return TestRunRecord(
        id=uuid.uuid4(),
        name=created_at.isoformat(),
        dataset_name="sample",
        config=TestRunConfig(),
        status=TestRunStatus.RUNNING,
        total=0,
        created_at=created_at,
        updated_at=created_at,
    )


def test_list_test_runs_defaults_to_newest_first() -> None:
    now = datetime.now(UTC)
    oldest = _run(now - timedelta(days=2))
    newest = _run(now)
    middle = _run(now - timedelta(days=1))
    # Insertion order deliberately not sorted - the repo (a DynamoDB scan
    # in production) has no defined order either.
    use_case = ListTestRunsUseCase(
        InMemoryTestRunRepository([middle, oldest, newest]),
        InMemoryWorkflowExecutionRepository(),
    )

    runs = use_case.execute()

    assert [r.id for r in runs] == [newest.id, middle.id, oldest.id]


def test_list_test_runs_order_asc_is_oldest_first() -> None:
    now = datetime.now(UTC)
    oldest = _run(now - timedelta(days=2))
    newest = _run(now)
    use_case = ListTestRunsUseCase(
        InMemoryTestRunRepository([newest, oldest]),
        InMemoryWorkflowExecutionRepository(),
    )

    runs = use_case.execute(order="asc")

    assert [r.id for r in runs] == [oldest.id, newest.id]

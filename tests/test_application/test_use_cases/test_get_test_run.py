from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.application.ports.test_run_port import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.application.use_cases.test_runs.get_test_run import GetTestRunUseCase


class InMemoryTestRunRepository:
    def __init__(self, runs: list[TestRunRecord]) -> None:
        self._runs = {r.id: r for r in runs}

    def create(self, run: TestRunRecord) -> TestRunRecord:
        self._runs[run.id] = run
        return run

    def get(self, run_id: UUID) -> TestRunRecord | None:
        return self._runs.get(run_id)

    def update(self, run_id: UUID, **changes: Any) -> TestRunRecord | None:
        raise NotImplementedError

    def list(self) -> list[TestRunRecord]:
        return list(self._runs.values())


class InMemoryWorkflowExecutionRepository:
    def __init__(self, workflows: list[WorkflowExecutionRecord]) -> None:
        self._workflows = workflows

    def create(self, workflow):
        raise NotImplementedError

    def get(self, workflow_id):
        raise NotImplementedError

    def update(self, workflow_id, **changes):
        raise NotImplementedError

    def list_by_test_run(self, test_run_id: UUID) -> list[WorkflowExecutionRecord]:
        return [w for w in self._workflows if w.test_run_id == test_run_id]


class InMemoryWorkflowStepExecutionRepository:
    def __init__(self, steps: list[WorkflowStepExecutionRecord]) -> None:
        self._steps = steps

    def create(self, step):
        raise NotImplementedError

    def get(self, workflow_execution_id, step_execution_id):
        raise NotImplementedError

    def update(self, workflow_execution_id, step_execution_id, **changes):
        raise NotImplementedError

    def list_by_workflow(
        self, workflow_execution_id: UUID
    ) -> list[WorkflowStepExecutionRecord]:
        return [
            s for s in self._steps if s.workflow_execution_id == workflow_execution_id
        ]


def _step(
    workflow_execution_id: UUID, input_tokens: int, output_tokens: int
) -> WorkflowStepExecutionRecord:
    now = datetime.now(timezone.utc)
    return WorkflowStepExecutionRecord(
        id=uuid.uuid4(),
        workflow_execution_id=workflow_execution_id,
        step_name="classification",
        status=WorkflowStepStatus.SUCCEEDED,
        attempt=1,
        input={},
        output={"input_tokens": input_tokens, "output_tokens": output_tokens},
        error=None,
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


def _workflow(status: WorkflowStatus, test_run_id: UUID) -> WorkflowExecutionRecord:
    now = datetime.now(timezone.utc)
    return WorkflowExecutionRecord(
        id=uuid.uuid4(),
        alert_id=uuid.uuid4(),
        async_operation_id=uuid.uuid4(),
        workflow_name="massive_fraud_alert_review",
        status=status,
        input={},
        output=None,
        error=None,
        current_step=None,
        feedback_iterations=0,
        max_feedback_iterations=2,
        created_at=now,
        updated_at=now,
        test_run_id=test_run_id,
    )


def test_get_test_run_rolls_up_case_statuses() -> None:
    now = datetime.now(timezone.utc)
    test_run_id = uuid.uuid4()
    test_run = TestRunRecord(
        id=test_run_id,
        name="run",
        dataset_name="sample",
        config=TestRunConfig(),
        status=TestRunStatus.RUNNING,
        total=4,
        created_at=now,
        updated_at=now,
    )
    workflows = [
        _workflow(WorkflowStatus.SUCCEEDED, test_run_id),
        _workflow(WorkflowStatus.SUCCEEDED, test_run_id),
        _workflow(WorkflowStatus.FAILED, test_run_id),
        _workflow(WorkflowStatus.RUNNING, test_run_id),
        _workflow(WorkflowStatus.SUCCEEDED, uuid.uuid4()),  # different run
    ]
    use_case = GetTestRunUseCase(
        test_run_repository=InMemoryTestRunRepository([test_run]),
        workflow_repository=InMemoryWorkflowExecutionRepository(workflows),
        step_repository=InMemoryWorkflowStepExecutionRepository([]),
    )

    detail = use_case.execute(test_run_id)

    assert detail is not None
    assert detail.total == 4
    assert detail.succeeded == 2
    assert detail.failed == 1
    assert detail.running == 1
    assert detail.pending == 0
    assert len(detail.cases) == 4


def test_get_test_run_sums_tokens_across_every_case_and_step() -> None:
    now = datetime.now(timezone.utc)
    test_run_id = uuid.uuid4()
    test_run = TestRunRecord(
        id=test_run_id,
        name="run",
        dataset_name="sample",
        config=TestRunConfig(),
        status=TestRunStatus.RUNNING,
        total=2,
        created_at=now,
        updated_at=now,
    )
    case_a = _workflow(WorkflowStatus.SUCCEEDED, test_run_id)
    case_b = _workflow(WorkflowStatus.SUCCEEDED, test_run_id)
    other_run_case = _workflow(WorkflowStatus.SUCCEEDED, uuid.uuid4())
    steps = [
        _step(case_a.id, input_tokens=100, output_tokens=20),
        _step(case_a.id, input_tokens=50, output_tokens=10),
        _step(case_b.id, input_tokens=200, output_tokens=40),
        # A different test run's case - must not leak into this total.
        _step(other_run_case.id, input_tokens=9_999, output_tokens=9_999),
    ]
    use_case = GetTestRunUseCase(
        test_run_repository=InMemoryTestRunRepository([test_run]),
        workflow_repository=InMemoryWorkflowExecutionRepository(
            [case_a, case_b, other_run_case]
        ),
        step_repository=InMemoryWorkflowStepExecutionRepository(steps),
    )

    detail = use_case.execute(test_run_id)

    assert detail is not None
    assert detail.input_tokens == 350
    assert detail.output_tokens == 70


def test_get_test_run_derives_status_from_cases_not_stored_field() -> None:
    # TestRunRecord.status is only ever written once, at dispatch time, and
    # never updated again as cases finish - regression test for that
    # staleness: a run stuck at the stored RUNNING must report FAILED once
    # every case is terminal and at least one failed, and SUCCEEDED once
    # every case is terminal and none failed.
    now = datetime.now(timezone.utc)

    def _run(run_id: UUID, total: int) -> TestRunRecord:
        return TestRunRecord(
            id=run_id,
            name="run",
            dataset_name="sample",
            config=TestRunConfig(),
            status=TestRunStatus.RUNNING,
            total=total,
            created_at=now,
            updated_at=now,
        )

    failed_run_id = uuid.uuid4()
    succeeded_run_id = uuid.uuid4()
    workflows = [
        _workflow(WorkflowStatus.SUCCEEDED, failed_run_id),
        _workflow(WorkflowStatus.FAILED, failed_run_id),
        _workflow(WorkflowStatus.SUCCEEDED, succeeded_run_id),
        _workflow(WorkflowStatus.SUCCEEDED, succeeded_run_id),
    ]
    use_case = GetTestRunUseCase(
        test_run_repository=InMemoryTestRunRepository(
            [_run(failed_run_id, 2), _run(succeeded_run_id, 2)]
        ),
        workflow_repository=InMemoryWorkflowExecutionRepository(workflows),
        step_repository=InMemoryWorkflowStepExecutionRepository([]),
    )

    failed_detail = use_case.execute(failed_run_id)
    succeeded_detail = use_case.execute(succeeded_run_id)

    assert failed_detail is not None
    assert failed_detail.status == TestRunStatus.FAILED
    assert succeeded_detail is not None
    assert succeeded_detail.status == TestRunStatus.SUCCEEDED


def test_get_test_run_returns_none_when_missing() -> None:
    use_case = GetTestRunUseCase(
        test_run_repository=InMemoryTestRunRepository([]),
        workflow_repository=InMemoryWorkflowExecutionRepository([]),
        step_repository=InMemoryWorkflowStepExecutionRepository([]),
    )
    assert use_case.execute(uuid.uuid4()) is None

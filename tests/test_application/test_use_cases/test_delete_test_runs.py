from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from src.application.dtos.test_run_dtos import DeleteTestRunsInput
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.ports.test_run_port import TestRunRecord
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsUseCase
from src.domain.alerts.entities import (
    AlertRecord,
    AlertStatus,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)


class InMemoryTestRunRepository:
    def __init__(self, runs: list[TestRunRecord]) -> None:
        self.runs: dict[UUID, TestRunRecord] = {r.id: r for r in runs}

    def create(self, run):
        raise NotImplementedError

    def get(self, run_id):
        return self.runs.get(run_id)

    def update(self, run_id, **changes):
        raise NotImplementedError

    def list(self) -> list[TestRunRecord]:
        return list(self.runs.values())

    def delete(self, run_id: UUID) -> None:
        self.runs.pop(run_id, None)


class InMemoryWorkflowExecutionRepository:
    def __init__(self, workflows: list[WorkflowExecutionRecord]) -> None:
        self.workflows: dict[UUID, WorkflowExecutionRecord] = {
            w.id: w for w in workflows
        }

    def create(self, workflow):
        raise NotImplementedError

    def get(self, workflow_id):
        return self.workflows.get(workflow_id)

    def update(self, workflow_id, **changes):
        raise NotImplementedError

    def list_by_test_run(self, test_run_id: UUID) -> list[WorkflowExecutionRecord]:
        return [w for w in self.workflows.values() if w.test_run_id == test_run_id]

    def delete(self, workflow_id: UUID) -> None:
        self.workflows.pop(workflow_id, None)


class InMemoryWorkflowStepExecutionRepository:
    def __init__(self, steps: list[WorkflowStepExecutionRecord]) -> None:
        self.steps: dict[UUID, WorkflowStepExecutionRecord] = {s.id: s for s in steps}

    def create(self, step):
        raise NotImplementedError

    def get(self, workflow_execution_id, step_id):
        raise NotImplementedError

    def list_by_workflow(
        self, workflow_execution_id: UUID
    ) -> list[WorkflowStepExecutionRecord]:
        return [
            s
            for s in self.steps.values()
            if s.workflow_execution_id == workflow_execution_id
        ]

    def update(self, workflow_execution_id, step_id, **changes):
        raise NotImplementedError

    def delete(self, workflow_execution_id: UUID, step_id: UUID) -> None:
        self.steps.pop(step_id, None)


class InMemoryAlertRepository:
    def __init__(self, alerts: list[AlertRecord]) -> None:
        self.alerts: dict[UUID, AlertRecord] = {a.id: a for a in alerts}

    def create(self, alert):
        raise NotImplementedError

    def get(self, alert_id):
        return self.alerts.get(alert_id)

    def update(self, alert_id, **changes):
        raise NotImplementedError

    def delete(self, alert_id: UUID) -> None:
        self.alerts.pop(alert_id, None)


class InMemoryAsyncOperationRepository:
    def __init__(self, operations: list[AsyncOperationRecord]) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {
            o.id: o for o in operations
        }

    def create(self, operation):
        raise NotImplementedError

    def get(self, operation_id):
        return self.operations.get(operation_id)

    def list(self, status=None, limit: int = 100):
        raise NotImplementedError

    def list_active(self, limit: int = 100):
        raise NotImplementedError

    def update(self, operation_id, **changes):
        raise NotImplementedError

    def delete(self, operation_id: UUID) -> None:
        self.operations.pop(operation_id, None)


def _test_run(total: int) -> TestRunRecord:
    from src.application.ports.test_run_port import TestRunConfig, TestRunStatus

    now = datetime.now(UTC)
    return TestRunRecord(
        id=uuid.uuid4(),
        name="run",
        dataset_name="sample",
        config=TestRunConfig(),
        status=TestRunStatus.SUCCEEDED,
        total=total,
        created_at=now,
        updated_at=now,
    )


def _case(
    test_run_id: UUID,
) -> tuple[
    WorkflowExecutionRecord,
    list[WorkflowStepExecutionRecord],
    AlertRecord,
    AsyncOperationRecord,
]:
    now = datetime.now(UTC)
    alert_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    workflow = WorkflowExecutionRecord(
        id=uuid.uuid4(),
        alert_id=alert_id,
        async_operation_id=operation_id,
        workflow_name="massive_fraud_alert_review",
        status=WorkflowStatus.SUCCEEDED,
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
    steps = [
        WorkflowStepExecutionRecord(
            id=uuid.uuid4(),
            workflow_execution_id=workflow.id,
            step_name=name,
            status=WorkflowStepStatus.SUCCEEDED,
            attempt=1,
            input={},
            output={},
            error=None,
            started_at=now,
            finished_at=now,
            created_at=now,
            updated_at=now,
        )
        for name in ("pre_process", "classification")
    ]
    alert = AlertRecord(
        id=alert_id,
        event_id="e-1",
        event_type="test",
        input={},
        status=AlertStatus.CLOSED,
        created_at=now,
        updated_at=now,
    )
    operation = AsyncOperationRecord(
        id=operation_id,
        operation_type="workflow.massive_fraud_alert_review",
        status=AsyncOperationStatus.SUCCEEDED,
        payload={},
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
    )
    return workflow, steps, alert, operation


def test_delete_test_runs_cascades_to_cases_steps_alerts_and_operations() -> None:
    test_run = _test_run(total=1)
    other_run = _test_run(total=1)
    workflow, steps, alert, operation = _case(test_run.id)
    other_workflow, other_steps, other_alert, other_operation = _case(other_run.id)

    test_runs = InMemoryTestRunRepository([test_run, other_run])
    workflows = InMemoryWorkflowExecutionRepository([workflow, other_workflow])
    step_repo = InMemoryWorkflowStepExecutionRepository(steps + other_steps)
    alerts = InMemoryAlertRepository([alert, other_alert])
    operations = InMemoryAsyncOperationRepository([operation, other_operation])

    use_case = DeleteTestRunsUseCase(
        test_run_repository=test_runs,
        workflow_repository=workflows,
        step_repository=step_repo,
        alert_repository=alerts,
        async_operation_repository=operations,
    )

    result = use_case.execute(DeleteTestRunsInput(test_run_ids=[test_run.id]))

    assert result.deleted_test_runs == 1
    assert result.deleted_cases == 1

    # This run's everything is gone...
    assert test_runs.get(test_run.id) is None
    assert workflows.get(workflow.id) is None
    assert step_repo.list_by_workflow(workflow.id) == []
    assert alerts.get(alert.id) is None
    assert operations.get(operation.id) is None

    # ...but the other test run is untouched.
    assert test_runs.get(other_run.id) is not None
    assert workflows.get(other_workflow.id) is not None
    assert len(step_repo.list_by_workflow(other_workflow.id)) == 2
    assert alerts.get(other_alert.id) is not None
    assert operations.get(other_operation.id) is not None


def test_delete_test_runs_handles_multiple_ids_and_missing_run() -> None:
    run_a = _test_run(total=0)
    run_b = _test_run(total=0)
    test_runs = InMemoryTestRunRepository([run_a, run_b])
    use_case = DeleteTestRunsUseCase(
        test_run_repository=test_runs,
        workflow_repository=InMemoryWorkflowExecutionRepository([]),
        step_repository=InMemoryWorkflowStepExecutionRepository([]),
        alert_repository=InMemoryAlertRepository([]),
        async_operation_repository=InMemoryAsyncOperationRepository([]),
    )

    result = use_case.execute(
        DeleteTestRunsInput(test_run_ids=[run_a.id, run_b.id, uuid.uuid4()])
    )

    assert result.deleted_test_runs == 3
    assert result.deleted_cases == 0
    assert test_runs.list() == []

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.application.dtos.test_run_dtos import StartTestRunInput
from src.application.use_cases.test_runs.dataset_sampling import (
    InsufficientSampleDataError,
)
from src.application.ports.alert_port import AlertRecord
from src.application.ports.async_operation_port import AsyncOperationRecord
from src.application.ports.dataset_port import DatasetRecord
from src.application.ports.test_run_port import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)
from src.application.ports.workflow_executor_port import (
    WorkflowExecutionRef,
    WorkflowExecutor,
)
from src.application.ports.workflow_port import WorkflowExecutionRecord
from src.application.use_cases.test_runs.start_test_run import StartTestRunUseCase


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def update(self, alert_id: UUID, **changes: Any) -> AlertRecord | None:
        alert = self.alerts.get(alert_id)
        if alert is None:
            return None
        updated = AlertRecord(
            id=alert.id,
            event_id=alert.event_id,
            event_type=alert.event_type,
            payload=alert.payload,
            status=changes.get("status") or alert.status,
            customer_id=alert.customer_id,
            async_operation_id=changes.get("async_operation_id")
            or alert.async_operation_id,
            workflow_execution_id=changes.get("workflow_execution_id")
            or alert.workflow_execution_id,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )
        self.alerts[alert_id] = updated
        return updated


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {}

    def create(self, operation: AsyncOperationRecord) -> AsyncOperationRecord:
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        return self.operations.get(operation_id)

    def list(self, status=None, limit: int = 100) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def update(self, operation_id: UUID, **changes: Any) -> AsyncOperationRecord | None:
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        updated = AsyncOperationRecord(
            id=operation.id,
            operation_type=operation.operation_type,
            status=changes.get("status") or operation.status,
            payload=operation.payload,
            result=operation.result,
            error=operation.error,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            created_by=operation.created_by,
            dispatched_at=changes.get("dispatched_at") or operation.dispatched_at,
            execution_backend=changes.get("execution_backend")
            or operation.execution_backend,
            external_id=changes.get("external_id") or operation.external_id,
        )
        self.operations[operation_id] = updated
        return updated


class InMemoryWorkflowExecutionRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, WorkflowExecutionRecord] = {}

    def create(self, workflow: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        self.workflows[workflow.id] = workflow
        return workflow

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        return self.workflows.get(workflow_id)

    def update(self, workflow_id: UUID, **changes: Any) -> WorkflowExecutionRecord | None:
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return None
        updated = WorkflowExecutionRecord(
            id=workflow.id,
            alert_id=workflow.alert_id,
            async_operation_id=workflow.async_operation_id,
            workflow_name=workflow.workflow_name,
            status=changes.get("status") or workflow.status,
            input=workflow.input,
            output=changes.get("output") or workflow.output,
            error=changes.get("error") or workflow.error,
            current_step=changes.get("current_step", workflow.current_step),
            feedback_iterations=changes.get(
                "feedback_iterations", workflow.feedback_iterations
            ),
            max_feedback_iterations=workflow.max_feedback_iterations,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            finished_at=changes.get("finished_at") or workflow.finished_at,
            execution_backend=changes.get("execution_backend")
            or workflow.execution_backend,
            external_id=changes.get("external_id") or workflow.external_id,
            test_run_id=workflow.test_run_id,
        )
        self.workflows[workflow_id] = updated
        return updated

    def list_by_test_run(self, test_run_id: UUID) -> list[WorkflowExecutionRecord]:
        return [w for w in self.workflows.values() if w.test_run_id == test_run_id]


class InMemoryTestRunRepository:
    def __init__(self) -> None:
        self.runs: dict[UUID, TestRunRecord] = {}

    def create(self, run: TestRunRecord) -> TestRunRecord:
        self.runs[run.id] = run
        return run

    def get(self, run_id: UUID) -> TestRunRecord | None:
        return self.runs.get(run_id)

    def update(self, run_id: UUID, **changes: Any) -> TestRunRecord | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        updated = TestRunRecord(
            id=run.id,
            name=run.name,
            dataset_name=run.dataset_name,
            config=run.config,
            status=changes.get("status") or run.status,
            total=run.total,
            created_at=run.created_at,
            updated_at=run.updated_at,
            finished_at=changes.get("finished_at") or run.finished_at,
        )
        self.runs[run_id] = updated
        return updated

    def list(self) -> list[TestRunRecord]:
        return list(self.runs.values())


class InMemoryDatasetRepository:
    def __init__(self, rows_by_name: dict[str, list[dict[str, Any]]]) -> None:
        self._rows_by_name = rows_by_name

    def list(self) -> list[DatasetRecord]:
        return [
            DatasetRecord(name=name, row_count=len(rows))
            for name, rows in self._rows_by_name.items()
        ]

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return self._rows_by_name[name]


class RecordingWorkflowExecutor(WorkflowExecutor):
    def __init__(self) -> None:
        self.started: list[WorkflowExecutionRecord] = []

    def start(self, workflow: WorkflowExecutionRecord) -> WorkflowExecutionRef:
        self.started.append(workflow)
        return WorkflowExecutionRef(backend="celery", external_id=f"task-{len(self.started)}")


def test_start_test_run_dispatches_one_workflow_per_dataset_row() -> None:
    datasets = InMemoryDatasetRepository(
        {
            "sample": [
                {"eventId": "e-1", "customerId": "c-1"},
                {"eventId": "e-2", "customerId": "c-2"},
            ]
        }
    )
    test_runs = InMemoryTestRunRepository()
    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    executor = RecordingWorkflowExecutor()
    use_case = StartTestRunUseCase(
        dataset_repository=datasets,
        test_run_repository=test_runs,
        alert_repository=alerts,
        async_operation_repository=operations,
        workflow_repository=workflows,
        workflow_executor=executor,
    )

    output = use_case.execute(
        StartTestRunInput(
            name="my run",
            dataset_name="sample",
            config=TestRunConfig(
                prompt_overrides={"classification": "custom prompt"},
                model_overrides={"classification": "gpt-test"},
            ),
        )
    )

    assert output.dispatched_count == 2
    test_run = test_runs.get(output.test_run_id)
    assert test_run.status == TestRunStatus.RUNNING
    assert test_run.total == 2

    dispatched = workflows.list_by_test_run(output.test_run_id)
    assert len(dispatched) == 2
    assert len(executor.started) == 2
    for workflow in dispatched:
        assert workflow.test_run_id == output.test_run_id
        assert workflow.input["config_overrides"]["prompt_overrides"] == {
            "classification": "custom prompt"
        }
        assert workflow.input["config_overrides"]["model_overrides"] == {
            "classification": "gpt-test"
        }


def _use_case(
    rows_by_name: dict[str, list[dict[str, Any]]],
) -> tuple[StartTestRunUseCase, InMemoryTestRunRepository, InMemoryWorkflowExecutionRepository]:
    test_runs = InMemoryTestRunRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    use_case = StartTestRunUseCase(
        dataset_repository=InMemoryDatasetRepository(rows_by_name),
        test_run_repository=test_runs,
        alert_repository=InMemoryAlertRepository(),
        async_operation_repository=InMemoryAsyncOperationRepository(),
        workflow_repository=workflows,
        workflow_executor=RecordingWorkflowExecutor(),
    )
    return use_case, test_runs, workflows


def _labeled_rows(counts: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for marcacion, n in counts.items():
        for i in range(n):
            rows.append({"eventId": f"e-{marcacion}-{i}", "marcacion_final": marcacion})
    return rows


def test_start_test_run_without_sample_size_dispatches_every_row() -> None:
    rows = _labeled_rows({"no-risk": 5, "risk": 2, "risk-suspected": 1})
    use_case, test_runs, _ = _use_case({"sample": rows})

    output = use_case.execute(
        StartTestRunInput(name="run", dataset_name="sample")
    )

    assert output.dispatched_count == 8
    assert test_runs.get(output.test_run_id).total == 8


def test_start_test_run_with_sample_size_mirrors_natural_distribution() -> None:
    rows = _labeled_rows({"no-risk": 80, "risk-suspected": 15, "risk": 5})
    use_case, _, workflows = _use_case({"sample": rows})

    output = use_case.execute(
        StartTestRunInput(name="run", dataset_name="sample", sample_size=20)
    )

    assert output.dispatched_count == 20
    dispatched = workflows.list_by_test_run(output.test_run_id)
    marcaciones = Counter(w.input["alert_payload"]["marcacion_final"] for w in dispatched)
    # 80/15/5 % of 100 source rows -> 16/3/1 of a 20-row sample.
    assert marcaciones == {"no-risk": 16, "risk-suspected": 3, "risk": 1}


def test_start_test_run_with_explicit_distribution_overrides_natural_shape() -> None:
    rows = _labeled_rows({"no-risk": 80, "risk-suspected": 15, "risk": 5})
    use_case, _, workflows = _use_case({"sample": rows})

    output = use_case.execute(
        StartTestRunInput(
            name="run",
            dataset_name="sample",
            sample_size=10,
            sample_distribution={
                "no-risk": 0.34,
                "risk-suspected": 0.33,
                "risk": 0.33,
            },
        )
    )

    assert output.dispatched_count == 10
    dispatched = workflows.list_by_test_run(output.test_run_id)
    marcaciones = Counter(w.input["alert_payload"]["marcacion_final"] for w in dispatched)
    assert marcaciones == {"no-risk": 4, "risk-suspected": 3, "risk": 3}


def test_start_test_run_raises_and_dispatches_nothing_when_class_underfilled() -> None:
    rows = _labeled_rows({"no-risk": 5, "risk": 1, "risk-suspected": 1})
    use_case, test_runs, workflows = _use_case({"sample": rows})

    with pytest.raises(InsufficientSampleDataError):
        use_case.execute(
            StartTestRunInput(
                name="run",
                dataset_name="sample",
                sample_size=10,
                sample_distribution={
                    "no-risk": 0.34,
                    "risk-suspected": 0.33,
                    "risk": 0.33,
                },
            )
        )

    assert test_runs.list() == []
    assert workflows.workflows == {}


def test_start_test_run_rejects_distribution_without_sample_size() -> None:
    use_case, _, _ = _use_case({"sample": _labeled_rows({"no-risk": 1})})

    with pytest.raises(ValueError):
        use_case.execute(
            StartTestRunInput(
                name="run",
                dataset_name="sample",
                sample_distribution={"no-risk": 1.0},
            )
        )

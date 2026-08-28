from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone

from src.application.dtos.alert_dtos import StartAlertWorkflowInput
from src.application.dtos.test_run_dtos import StartTestRunInput, StartTestRunOutput
from src.application.ports.alert_port import AlertRepository
from src.application.ports.async_operation_port import AsyncOperationRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.test_run_port import (
    TestRunRecord,
    TestRunRepository,
    TestRunStatus,
)
from src.application.ports.workflow_executor_port import WorkflowExecutor
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.application.use_cases.test_runs.dataset_sampling import sample_rows


class StartTestRunUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        test_run_repository: TestRunRepository,
        alert_repository: AlertRepository,
        async_operation_repository: AsyncOperationRepository,
        workflow_repository: WorkflowExecutionRepository,
        workflow_executor: WorkflowExecutor,
    ) -> None:
        self._datasets = dataset_repository
        self._test_runs = test_run_repository
        # Reused as-is, not re-derived: this already builds the exact
        # alert/async-operation/workflow triad + dispatch a test case needs
        # (see start_alert_test_workflow.py) - a batch run is just that,
        # looped, with test_run_id/config_overrides threaded through.
        self._start_alert = StartAlertTestWorkflowUseCase(
            alert_repository=alert_repository,
            async_operation_repository=async_operation_repository,
            workflow_repository=workflow_repository,
            workflow_executor=workflow_executor,
        )

    def execute(self, input: StartTestRunInput) -> StartTestRunOutput:
        rows = self._datasets.get_rows(input.dataset_name)
        if input.sample_distribution is not None and input.sample_size is None:
            raise ValueError("sample_distribution requires sample_size")
        if input.sample_size is not None:
            rows = sample_rows(
                rows, size=input.sample_size, distribution=input.sample_distribution
            )
        now = datetime.now(timezone.utc)
        test_run = self._test_runs.create(
            TestRunRecord(
                id=uuid.uuid4(),
                name=input.name,
                dataset_name=input.dataset_name,
                config=input.config,
                status=TestRunStatus.PENDING,
                total=len(rows),
                created_at=now,
                updated_at=now,
            )
        )
        # config_overrides only ever carries the per-step string patches
        # (_step_overrides in alert_review_workflow.py reads just
        # prompt_overrides/model_overrides from it) - configuration_ref is
        # a whole-config selection threaded separately below, not folded
        # into this blob.
        config_overrides = dataclasses.asdict(input.config)
        config_overrides.pop("configuration_ref", None)
        for row in rows:
            self._start_alert.execute(
                StartAlertWorkflowInput(
                    payload=row,
                    test_run_id=test_run.id,
                    config_overrides=config_overrides,
                    max_feedback_iterations=input.config.max_feedback_iterations,
                    configuration_ref=input.config.configuration_ref,
                )
            )
        self._test_runs.update(test_run.id, status=TestRunStatus.RUNNING)
        return StartTestRunOutput(
            test_run_id=test_run.id,
            dispatched_count=len(rows),
        )

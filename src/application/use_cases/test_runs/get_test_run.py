from __future__ import annotations

from uuid import UUID

from src.application.dtos.test_run_dtos import TestCaseSummary, TestRunDetail
from src.application.ports.alert_port import AlertRepository
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.test_run_port import TestRunRepository
from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStepExecutionRepository,
)
from src.application.use_cases.test_runs.classification_metrics import (
    compute_analyst_agreement_metrics,
    compute_ground_truth_metrics,
)
from src.application.use_cases.test_runs.dataset_sampling import (
    MARCACION_FIELD,
    TIPO_FIELD,
)
from src.application.use_cases.test_runs.duration_stats import (
    compute_stats,
    step_duration_stats_by_name,
    workflow_duration,
)
from src.application.use_cases.test_runs.token_usage import sum_step_tokens
from src.domain.test_runs.entities import TestRunStatus
from src.domain.workflows.entities import (
    WorkflowStatus,
    WorkflowStepExecutionRecord,
)

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
        return TestRunStatus.SUCCEEDED
    if succeeded + failed < total:
        return TestRunStatus.FAILED
    # A test run reports execution completion, not business success of each
    # alert classification. Per-case outcomes remain available in `failed`.
    return TestRunStatus.SUCCEEDED


class GetTestRunUseCase:
    def __init__(
        self,
        test_run_repository: TestRunRepository,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
        alert_repository: AlertRepository | None = None,
        schema_repository: AlertSchemaRepository | None = None,
    ) -> None:
        self._test_runs = test_run_repository
        self._workflows = workflow_repository
        self._steps = step_repository
        self._alerts = alert_repository
        self._schemas = schema_repository

    def execute(self, test_run_id: UUID) -> TestRunDetail | None:
        test_run = self._test_runs.get(test_run_id)
        if test_run is None:
            return None

        workflows = self._workflows.list_by_test_run(test_run_id)
        succeeded = sum(1 for w in workflows if w.status == WorkflowStatus.SUCCEEDED)
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
        all_steps: list[WorkflowStepExecutionRecord] = []
        analyst_cases: list[tuple[str | None, str | None]] = []
        ground_truth_cases: list[tuple[str | None, str | None]] = []
        for w in workflows:
            steps = self._steps.list_by_workflow(w.id)
            all_steps.extend(steps)
            step_input, step_output = sum_step_tokens(steps)
            input_tokens += step_input
            output_tokens += step_output

            output = _final_classification_output(steps)
            labels = _canonical_evaluation_labels(
                w.alert_id, self._alerts, self._schemas
            )
            if labels is not None and output is not None:
                is_fraud = output.get("is_fraud")
                analyst_cases.append((labels.get(MARCACION_FIELD), is_fraud))
                ground_truth_cases.append((labels.get(TIPO_FIELD), is_fraud))
            elif labels is None and output is not None:
                # Kept only for direct callers that have not wired the
                # canonical alert/schema ports. Production wiring always
                # takes the branch above.
                is_fraud = output.get("is_fraud")
                analyst_cases.append((output.get("expected_classification"), is_fraud))
                ground_truth_cases.append((output.get("ground_truth_tipo"), is_fraud))

        total_durations = [
            d for w in workflows if (d := workflow_duration(w)) is not None
        ]

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
                    duration_seconds=workflow_duration(w),
                )
                for w in workflows
            ],
            step_duration_stats=step_duration_stats_by_name(all_steps),
            total_duration_stats=compute_stats(total_durations),
            analyst_agreement_metrics=compute_analyst_agreement_metrics(analyst_cases),
            ground_truth_metrics=compute_ground_truth_metrics(ground_truth_cases),
        )


def _final_classification_output(
    steps: list[WorkflowStepExecutionRecord],
) -> dict | None:
    # A case may retry "classification" several times (adversarial
    # feedback loop, see AlertReviewWorkflowRunner._run_adversarial_review)
    # - each attempt is its own step record with the same step_name. Only
    # the highest-attempt one is the result that actually flowed downstream
    # (to adversarial/analyst/executor), so that's the one to score.
    classification_steps = [
        s for s in steps if s.step_name == "classification" and s.output
    ]
    if not classification_steps:
        return None
    return max(classification_steps, key=lambda s: s.attempt).output


def _canonical_evaluation_labels(
    alert_id: UUID,
    alerts: AlertRepository | None,
    schemas: AlertSchemaRepository | None,
) -> dict[str, object] | None:
    if alerts is None or schemas is None:
        return None
    alert = alerts.get(alert_id)
    if alert is None or alert.schema_version is None:
        return {}
    schema = schemas.get(alert.schema_version)
    if schema is None:
        return {}
    label_fields = {field.field for field in schema.fields if field.is_label}
    return {
        field: value for field, value in alert.labels.items() if field in label_fields
    }

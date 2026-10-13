"""RecordWorkflowStepMetrics (R8): the ONLY writer of the workflow_step,
llm_call and research_call rollups.

Called by the workflow runner when a run ends (success or failure), after
the step records are flushed. It reads the run's persisted step executions
- the same records test_runs/token_usage.py sums - and counts each finished
one exactly once:

Idempotency: every step execution record has its own id (a Celery retry of
the alert review re-runs the steps as NEW records, which really did run and
spend tokens, so they count too). Each record's deltas are applied with
MetricsRollupRepository.apply_once under the marker
("workflow_step", <step execution id>), written in the same transaction as
the ADDs. Re-recording the same run (the next Celery attempt lists the
previous attempt's steps again, a redelivered task, the escalation path
recording twice) finds the marker and the transaction is cancelled whole -
no step is ever counted twice, and a crash mid-loop leaves each step either
fully counted or not at all, to be picked up by the next call.

Dimensions: the alert's TECHNICAL_ALERT_DIMENSIONS as stored on its
metrics snapshot at the time of the call (so status / resolution_method are
the run's outcome: the runner records WORKFLOW_FINISHED first), plus
step_name / model / source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from src.application.dtos.technical_metrics_dtos import (
    RecordWorkflowStepMetricsInput,
    RecordWorkflowStepMetricsOutput,
)
from src.application.ports.alert_port import AlertRepository
from src.application.ports.metrics_rollup_port import (
    MetricsRollupRepository,
    RollupApplyMarker,
)
from src.application.ports.workflow_port import WorkflowStepExecutionRepository
from src.application.use_cases.metrics.technical_rollup_contribution import (
    is_finished,
    step_contributions,
    technical_alert_dimensions,
    technical_deltas,
)

MARKER_SCOPE = "workflow_step"


class RecordWorkflowStepMetrics:
    def __init__(
        self,
        alert_repository: AlertRepository,
        step_repository: WorkflowStepExecutionRepository,
        rollup_repository: MetricsRollupRepository,
        timezone_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._alerts = alert_repository
        self._steps = step_repository
        self._rollups = rollup_repository
        self._timezone_name = timezone_name
        self._clock = clock

    def execute(
        self, input: RecordWorkflowStepMetricsInput
    ) -> RecordWorkflowStepMetricsOutput:
        result = RecordWorkflowStepMetricsOutput()
        alert = self._alerts.get(input.alert_id)
        if alert is None:
            return result
        dimensions = technical_alert_dimensions(alert.metrics, alert.status)
        steps = sorted(
            self._steps.list_by_workflow(input.workflow_execution_id),
            key=lambda s: (s.created_at, str(s.id)),
        )
        seen: set[str] = set()
        for step in steps:
            # Any execution of a step name after its first one in this
            # workflow is a re-execution: an adversarial feedback loop or a
            # Celery retry re-running the pipeline.
            is_reexecution = step.step_name in seen
            seen.add(step.step_name)
            if not is_finished(step):
                result.not_finished += 1
                continue
            parts = step_contributions(
                step,
                dimensions,
                is_reexecution=is_reexecution,
                model=input.step_models.get(step.step_name),
            )
            deltas = technical_deltas(
                parts, alert.created_at, self._clock(), self._timezone_name
            )
            applied = self._rollups.apply_once(
                deltas, RollupApplyMarker(scope=MARKER_SCOPE, key=str(step.id))
            )
            if applied:
                result.recorded += 1
            else:
                result.already_recorded += 1
        return result

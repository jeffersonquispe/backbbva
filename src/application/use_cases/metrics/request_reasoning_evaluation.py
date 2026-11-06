"""RequestReasoningEvaluation: the evaluator's own intake.

Decides whether a finished alert gets judged and, if so, opens its evaluation
job and puts it on the evaluator's queue. The alert flow only announces that an
alert finished (or someone asks for it by hand); sampling, origin rules and the
job's state all live here, so the alert is resolved and visible whether or not
the evaluator runs, and an evaluator failure never reaches the alert."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from src.application.ports.alert_port import AlertRepository
from src.application.ports.clock_port import Clock
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.ports.reasoning_evaluation_job_dispatcher_port import (
    ReasoningEvaluationJobDispatcher,
)
from src.application.ports.reasoning_evaluation_job_port import (
    ACTIVE_STATUSES,
    ReasoningEvaluationJob,
    ReasoningEvaluationJobRepository,
    ReasoningEvaluationJobStatus,
)
from src.application.use_cases.metrics.evaluate_alert_reasoning import (
    is_sampled_for_evaluation,
)
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    UNJUDGED_ORIGINS,
    ReasoningEvaluationAlertNotFoundError,
)

REQUESTED_BY_WORKFLOW = "workflow"
REQUESTED_BY_MANUAL = "manual"


class RequestOutcome(StrEnum):
    QUEUED = "queued"
    # A job for this alert already exists (queued, running or done).
    EXISTING = "existing"
    NOT_SAMPLED = "not_sampled"
    NOT_APPLICABLE = "not_applicable"


class ReasoningEvaluationNotReadyError(Exception):
    """The alert has no finished workflow run to judge yet."""


@dataclass(frozen=True)
class RequestReasoningEvaluationOutput:
    outcome: RequestOutcome
    job: ReasoningEvaluationJob | None


class RequestReasoningEvaluation:
    def __init__(
        self,
        jobs: ReasoningEvaluationJobRepository,
        alerts: AlertRepository,
        settings: OperationalSettingsRepository,
        dispatcher: ReasoningEvaluationJobDispatcher,
        clock: Clock,
    ) -> None:
        self._jobs = jobs
        self._alerts = alerts
        self._settings = settings
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID | None = None,
        *,
        forced: bool = False,
    ) -> RequestReasoningEvaluationOutput:
        """``forced`` is a person asking for this alert: it skips sampling and
        may re-queue a failed or invalid job, but never a test or optimizer run."""
        existing = self._jobs.get(alert_id)
        if existing is not None and (
            existing.status in ACTIVE_STATUSES
            or existing.status == ReasoningEvaluationJobStatus.EVALUATED
            or not forced
        ):
            return RequestReasoningEvaluationOutput(RequestOutcome.EXISTING, existing)
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise ReasoningEvaluationAlertNotFoundError(str(alert_id))
        origin = alert.metrics.origin if alert.metrics is not None else None
        if (origin or "") in UNJUDGED_ORIGINS:
            return RequestReasoningEvaluationOutput(RequestOutcome.NOT_APPLICABLE, None)
        if not forced and not is_sampled_for_evaluation(
            alert_id, self._settings.get().reasoning_evaluation_sample_rate
        ):
            return RequestReasoningEvaluationOutput(RequestOutcome.NOT_SAMPLED, None)
        workflow_id = workflow_execution_id or alert.workflow_execution_id
        if workflow_id is None:
            raise ReasoningEvaluationNotReadyError(str(alert_id))
        job = ReasoningEvaluationJob(
            alert_id=alert_id,
            workflow_execution_id=workflow_id,
            status=ReasoningEvaluationJobStatus.QUEUED,
            requested_by=REQUESTED_BY_MANUAL if forced else REQUESTED_BY_WORKFLOW,
            queued_at=self._clock.now(),
        )
        stored = (
            self._jobs.requeue(job)
            if existing is not None
            else self._jobs.create_if_absent(job)
        )
        if not stored:  # lost a race with another request for the same alert
            return RequestReasoningEvaluationOutput(
                RequestOutcome.EXISTING, self._jobs.get(alert_id)
            )
        self._dispatcher.enqueue(alert_id, workflow_id)
        return RequestReasoningEvaluationOutput(RequestOutcome.QUEUED, job)

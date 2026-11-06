from __future__ import annotations

from uuid import UUID

from src.application.ports.reasoning_evaluation_dispatcher_port import (
    ReasoningEvaluationDispatcher,
    ReasoningEvaluationDispatchRef,
)
from src.application.ports.reasoning_evaluation_job_dispatcher_port import (
    ReasoningEvaluationJobDispatcher,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.queues.celery.app import app

# By task name (app.send_task), like the analyst-decision documenter: the
# tasks module imports AlertReviewWorkflowRunner, which uses this
# dispatcher, so importing the task function here would be circular.
# Both go to the evaluator's own queue: its worker is the only one that touches
# evaluation state, and a slow or down evaluator never queues behind (or blocks)
# alert processing.
_TASK_NAME = "metrics.request_reasoning_evaluation"
_RUN_TASK_NAME = "metrics.evaluate_alert_reasoning"


class CeleryReasoningEvaluationDispatcher(ReasoningEvaluationDispatcher):
    """What the alert flow calls: only announces that an alert finished."""

    def dispatch(
        self, alert_id: UUID, workflow_execution_id: UUID
    ) -> ReasoningEvaluationDispatchRef:
        result = app.send_task(
            _TASK_NAME,
            args=[str(alert_id), str(workflow_execution_id)],
            queue=genai_config.CELERY_REASONING_EVALUATION_QUEUE,
        )
        return ReasoningEvaluationDispatchRef(backend="celery", external_id=result.id)


class CeleryReasoningEvaluationJobDispatcher(ReasoningEvaluationJobDispatcher):
    """What the evaluator calls to run one of its own jobs."""

    def enqueue(self, alert_id: UUID, workflow_execution_id: UUID) -> None:
        app.send_task(
            _RUN_TASK_NAME,
            args=[str(alert_id), str(workflow_execution_id)],
            queue=genai_config.CELERY_REASONING_EVALUATION_QUEUE,
        )

from __future__ import annotations

from uuid import UUID

from src.application.ports.reasoning_evaluation_dispatcher_port import (
    ReasoningEvaluationDispatcher,
    ReasoningEvaluationDispatchRef,
)
from src.infrastructure.entrypoint.worker.celery.celery_app import app

# By task name (app.send_task), like the analyst-decision documenter: the
# tasks module imports AlertReviewWorkflowRunner, which uses this
# dispatcher, so importing the task function here would be circular.
_TASK_NAME = "metrics.evaluate_alert_reasoning"


class CeleryReasoningEvaluationDispatcher(ReasoningEvaluationDispatcher):
    def dispatch(
        self, alert_id: UUID, workflow_execution_id: UUID
    ) -> ReasoningEvaluationDispatchRef:
        result = app.send_task(
            _TASK_NAME, args=[str(alert_id), str(workflow_execution_id)]
        )
        return ReasoningEvaluationDispatchRef(backend="celery", external_id=result.id)

from __future__ import annotations

from uuid import UUID

from src.application.ports.analyst_escalation_port import (
    AnalystEscalationDispatcher,
    AnalystEscalationRef,
)
from src.infrastructure.queues.celery.app import app

# Dispatched by task name (app.send_task) rather than importing the task
# function from entrypoint.worker.celery.tasks: that module imports
# AlertReviewWorkflowRunner, which needs this dispatcher, so a direct
# import here would be circular.
_TASK_NAME = "workflows.alert_review.escalate_to_analyst"


class CeleryAnalystEscalationDispatcher(AnalystEscalationDispatcher):
    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        event_id: str,
        session_id: str | None,
        reason: str,
    ) -> AnalystEscalationRef:
        result = app.send_task(
            _TASK_NAME,
            args=[str(alert_id), event_id, session_id, reason],
        )
        return AnalystEscalationRef(backend="celery", external_id=result.id)

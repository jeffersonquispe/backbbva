from __future__ import annotations

from uuid import UUID

from src.application.ports.alert_action_dispatcher_port import (
    AlertActionDispatcher,
    AlertActionDispatchRef,
)
from src.infrastructure.entrypoint.worker.celery.celery_app import app

# Dispatched by task name (app.send_task) rather than importing the task
# function from entrypoint.worker.celery.tasks: that module imports
# AlertReviewWorkflowRunner, which needs this dispatcher, so a direct
# import here would be circular.
_TASK_NAME = "workflows.alert_review.execute_alert_action"


class CeleryAlertActionDispatcher(AlertActionDispatcher):
    def dispatch(
        self, action: str, alert_id: UUID, content: str | None = None
    ) -> AlertActionDispatchRef:
        result = app.send_task(_TASK_NAME, args=[action, str(alert_id), content])
        return AlertActionDispatchRef(backend="celery", external_id=result.id)

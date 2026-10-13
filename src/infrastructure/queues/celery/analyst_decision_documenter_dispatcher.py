from __future__ import annotations

from typing import Any
from uuid import UUID

from src.application.ports.analyst_decision_documenter_port import (
    AnalystDecisionDocumenter,
    DocumentationDispatchRef,
)
from src.infrastructure.queues.celery.app import app

# Dispatched by task name (app.send_task) rather than importing the task
# function from entrypoint.worker.celery.tasks: that module imports
# AlertReviewWorkflowRunner, which needs this dispatcher, so a direct
# import here would be circular.
_TASK_NAME = "workflows.alert_review.document_analyst_decision"


class CeleryAnalystDecisionDocumenter(AnalystDecisionDocumenter):
    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        steps: dict[str, dict[str, Any]],
    ) -> DocumentationDispatchRef:
        result = app.send_task(
            _TASK_NAME,
            args=[str(alert_id), str(workflow_execution_id), steps],
        )
        return DocumentationDispatchRef(backend="celery", external_id=result.id)

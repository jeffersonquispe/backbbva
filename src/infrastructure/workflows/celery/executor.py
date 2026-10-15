from __future__ import annotations

from src.application.ports.workflow_executor_port import (
    WorkflowExecutionRef,
    WorkflowExecutor,
)
from src.domain.alerts.entities import (
    AlertOrigin,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.queues.celery.app import app

# Dispatched by task name (app.send_task), same as
# CeleryAlertActionDispatcher: importing the task function would pull the
# whole worker module (alert_review_workflow.py and its ML/pandas deps)
# into aria-api, which runs from a different poetry project without them.
_TASK_NAME = "workflows.alert_review.run"


def queue_for_origin(origin: str | None) -> str:
    if origin == AlertOrigin.TEST_RUN.value:
        return genai_config.CELERY_TEST_QUEUE
    if origin == AlertOrigin.SIMULATOR.value:
        return genai_config.CELERY_SIMULATOR_ALERT_QUEUE
    return genai_config.CELERY_DEFAULT_QUEUE


class CeleryWorkflowExecutor(WorkflowExecutor):
    def start(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRef:
        origin = workflow.input.get("origin")
        result = app.send_task(
            _TASK_NAME, args=[str(workflow.id)], queue=queue_for_origin(origin)
        )
        return WorkflowExecutionRef(
            backend="celery",
            external_id=result.id,
        )

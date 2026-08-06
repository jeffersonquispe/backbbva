from __future__ import annotations

from src.application.ports.workflow_executor_port import (
    WorkflowExecutionRef,
    WorkflowExecutor,
)
from src.application.ports.workflow_port import WorkflowExecutionRecord
from src.infrastructure.queues.celery.tasks import run_alert_review_workflow


class CeleryWorkflowExecutor(WorkflowExecutor):
    def start(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRef:
        result = run_alert_review_workflow.delay(str(workflow.id))
        return WorkflowExecutionRef(
            backend="celery",
            external_id=result.id,
        )

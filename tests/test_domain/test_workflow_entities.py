from datetime import UTC, datetime
from uuid import uuid4

from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)


def test_workflow_records_preserve_status_and_execution_metadata() -> None:
    now = datetime.now(UTC)
    workflow_id = uuid4()
    workflow = WorkflowExecutionRecord(
        id=workflow_id,
        alert_id=uuid4(),
        async_operation_id=uuid4(),
        workflow_name="alert_review",
        status=WorkflowStatus.RUNNING,
        input={"schema_version": 4},
        output=None,
        error=None,
        current_step="classification",
        feedback_iterations=0,
        max_feedback_iterations=1,
        created_at=now,
        updated_at=now,
    )
    step = WorkflowStepExecutionRecord(
        id=uuid4(),
        workflow_execution_id=workflow_id,
        step_name="classification",
        status=WorkflowStepStatus.RUNNING,
        attempt=1,
        input=None,
        output=None,
        error=None,
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )

    assert workflow.status is WorkflowStatus.RUNNING
    assert workflow.input == {"schema_version": 4}
    assert step.workflow_execution_id == workflow.id
    assert step.status is WorkflowStepStatus.RUNNING

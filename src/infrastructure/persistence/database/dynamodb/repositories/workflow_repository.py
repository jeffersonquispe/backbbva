from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from boto3.dynamodb.conditions import Key

from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStepExecutionRepository,
)
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

WORKFLOW_TABLE_NAME = "workflow_executions"
WORKFLOW_PARTITION = "workflow"
STEP_TABLE_NAME = "workflow_step_executions"


class DynamoWorkflowExecutionRepository(WorkflowExecutionRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(WORKFLOW_TABLE_NAME)

    def create(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRecord:
        self._table.put_item(Item=_workflow_to_item(workflow))
        return workflow

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        response = self._table.get_item(
            Key={
                "partition": WORKFLOW_PARTITION,
                "workflow_execution_id": str(workflow_id),
            }
        )
        item = response.get("Item")
        if item is None:
            return None
        return _workflow_from_item(item)

    def update(
        self,
        workflow_id: UUID,
        *,
        status: WorkflowStatus | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        current_step: str | None = None,
        feedback_iterations: int | None = None,
        finished_at: datetime | None = None,
        execution_backend: str | None = None,
        external_id: str | None = None,
        schema_comparison: dict[str, Any] | None = None,
    ) -> WorkflowExecutionRecord | None:
        current = self.get(workflow_id)
        if current is None:
            return None

        updated = WorkflowExecutionRecord(
            id=current.id,
            alert_id=current.alert_id,
            async_operation_id=current.async_operation_id,
            workflow_name=current.workflow_name,
            status=status or current.status,
            input=current.input,
            output=output if output is not None else current.output,
            error=error if error is not None else current.error,
            current_step=(
                current_step if current_step is not None else current.current_step
            ),
            feedback_iterations=(
                feedback_iterations
                if feedback_iterations is not None
                else current.feedback_iterations
            ),
            max_feedback_iterations=current.max_feedback_iterations,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
            finished_at=finished_at or current.finished_at,
            execution_backend=execution_backend or current.execution_backend,
            external_id=external_id or current.external_id,
            test_run_id=current.test_run_id,
            schema_comparison=schema_comparison
            if schema_comparison is not None
            else current.schema_comparison,
        )
        self._table.put_item(Item=_workflow_to_item(updated))
        return updated

    def list_by_test_run(
        self,
        test_run_id: UUID,
    ) -> list[WorkflowExecutionRecord]:
        response = self._table.query(
            IndexName="TestRunIdx",
            KeyConditionExpression=Key("test_run_id").eq(str(test_run_id)),
        )
        return [_workflow_from_item(item) for item in response.get("Items", [])]

    def delete(self, workflow_id: UUID) -> None:
        self._table.delete_item(
            Key={
                "partition": WORKFLOW_PARTITION,
                "workflow_execution_id": str(workflow_id),
            }
        )


class DynamoWorkflowStepExecutionRepository(WorkflowStepExecutionRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(STEP_TABLE_NAME)

    def create(
        self,
        step: WorkflowStepExecutionRecord,
    ) -> WorkflowStepExecutionRecord:
        self._table.put_item(Item=_step_to_item(step))
        return step

    def get(
        self,
        workflow_execution_id: UUID,
        step_id: UUID,
    ) -> WorkflowStepExecutionRecord | None:
        response = self._table.get_item(
            Key={
                "workflow_execution_id": str(workflow_execution_id),
                "step_execution_id": str(step_id),
            }
        )
        item = response.get("Item")
        if item is None:
            return None
        return _step_from_item(item)

    def list_by_workflow(
        self,
        workflow_execution_id: UUID,
    ) -> list[WorkflowStepExecutionRecord]:
        response = self._table.query(
            KeyConditionExpression=Key("workflow_execution_id").eq(
                str(workflow_execution_id)
            ),
            ScanIndexForward=True,
        )
        return [_step_from_item(item) for item in response.get("Items", [])]

    def update(
        self,
        workflow_execution_id: UUID,
        step_id: UUID,
        *,
        status: WorkflowStepStatus | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> WorkflowStepExecutionRecord | None:
        current = self.get(workflow_execution_id, step_id)
        if current is None:
            return None
        updated = WorkflowStepExecutionRecord(
            id=current.id,
            workflow_execution_id=current.workflow_execution_id,
            step_name=current.step_name,
            status=status or current.status,
            attempt=current.attempt,
            input=current.input,
            output=output if output is not None else current.output,
            error=error if error is not None else current.error,
            started_at=started_at or current.started_at,
            finished_at=finished_at or current.finished_at,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
        )
        self._table.put_item(Item=_step_to_item(updated))
        return updated

    def delete(self, workflow_execution_id: UUID, step_id: UUID) -> None:
        self._table.delete_item(
            Key={
                "workflow_execution_id": str(workflow_execution_id),
                "step_execution_id": str(step_id),
            }
        )


def _workflow_to_item(workflow: WorkflowExecutionRecord) -> dict[str, Any]:
    item = {
        "partition": WORKFLOW_PARTITION,
        "workflow_execution_id": str(workflow.id),
        "alert_id": str(workflow.alert_id),
        "async_operation_id": str(workflow.async_operation_id),
        "workflow_name": workflow.workflow_name,
        "status": workflow.status.value,
        "input": to_dynamodb(workflow.input),
        "output": to_dynamodb(workflow.output),
        "error": workflow.error,
        "current_step": workflow.current_step,
        "feedback_iterations": workflow.feedback_iterations,
        "max_feedback_iterations": workflow.max_feedback_iterations,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
        "finished_at": (
            workflow.finished_at.isoformat() if workflow.finished_at else None
        ),
        "execution_backend": workflow.execution_backend,
        "external_id": workflow.external_id,
        "schema_comparison": to_dynamodb(workflow.schema_comparison),
    }
    # Omitted (not written as NULL) when unset, so the TestRunIdx GSI stays
    # sparse - only test-run-linked workflows should appear in it.
    if workflow.test_run_id is not None:
        item["test_run_id"] = str(workflow.test_run_id)
    return item


def _workflow_from_item(item: dict[str, Any]) -> WorkflowExecutionRecord:
    finished_at = item.get("finished_at")
    return WorkflowExecutionRecord(
        id=UUID(item["workflow_execution_id"]),
        alert_id=UUID(item["alert_id"]),
        async_operation_id=UUID(item["async_operation_id"]),
        workflow_name=item["workflow_name"],
        status=WorkflowStatus(item["status"]),
        input=from_dynamodb(item.get("input") or {}),
        output=from_dynamodb(item.get("output")),
        error=item.get("error"),
        current_step=item.get("current_step"),
        feedback_iterations=int(item.get("feedback_iterations") or 0),
        max_feedback_iterations=int(item.get("max_feedback_iterations") or 1),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        finished_at=datetime.fromisoformat(finished_at) if finished_at else None,
        execution_backend=item.get("execution_backend"),
        external_id=item.get("external_id"),
        test_run_id=(UUID(item["test_run_id"]) if item.get("test_run_id") else None),
        schema_comparison=from_dynamodb(item.get("schema_comparison")),
    )


def _step_to_item(step: WorkflowStepExecutionRecord) -> dict[str, Any]:
    return {
        "workflow_execution_id": str(step.workflow_execution_id),
        "step_execution_id": str(step.id),
        "step_name": step.step_name,
        "status": step.status.value,
        "attempt": step.attempt,
        "input": to_dynamodb(step.input),
        "output": to_dynamodb(step.output),
        "error": step.error,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "finished_at": (step.finished_at.isoformat() if step.finished_at else None),
        "created_at": step.created_at.isoformat(),
        "updated_at": step.updated_at.isoformat(),
    }


def _step_from_item(item: dict[str, Any]) -> WorkflowStepExecutionRecord:
    started_at = item.get("started_at")
    finished_at = item.get("finished_at")
    return WorkflowStepExecutionRecord(
        id=UUID(item["step_execution_id"]),
        workflow_execution_id=UUID(item["workflow_execution_id"]),
        step_name=item["step_name"],
        status=WorkflowStepStatus(item["status"]),
        attempt=int(item.get("attempt") or 1),
        input=from_dynamodb(item.get("input")),
        output=from_dynamodb(item.get("output")),
        error=item.get("error"),
        started_at=datetime.fromisoformat(started_at) if started_at else None,
        finished_at=(datetime.fromisoformat(finished_at) if finished_at else None),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.application.ports.alert_port import AlertStatus
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowExecutionRepository,
    DynamoWorkflowStepExecutionRepository,
)

LINEAR_STEPS = (
    "pre_process",
    "profiling",
    "classification",
    "adversarial",
    "analyst",
    "executor",
    "post_process",
)


class AlertReviewWorkflowRunner:
    def __init__(self) -> None:
        self._alerts = DynamoAlertRepository()
        self._operations = DynamoAsyncOperationRepository()
        self._workflows = DynamoWorkflowExecutionRepository()
        self._steps = DynamoWorkflowStepExecutionRepository()

    def run(self, workflow_execution_id: UUID) -> dict[str, Any]:
        workflow = self._workflows.get(workflow_execution_id)
        if workflow is None:
            return {
                "status": "not_found",
                "workflow_execution_id": str(workflow_execution_id),
            }

        self._operations.update(
            workflow.async_operation_id,
            status=AsyncOperationStatus.RUNNING,
        )
        self._workflows.update(
            workflow.id,
            status=WorkflowStatus.RUNNING,
        )

        context: dict[str, Any] = {
            "workflow_execution_id": str(workflow.id),
            "alert_id": str(workflow.alert_id),
            "async_operation_id": str(workflow.async_operation_id),
            "input": workflow.input,
            "classification_attempt": 1,
        }

        try:
            for step_name in LINEAR_STEPS:
                if step_name == "classification":
                    context = self._run_step(workflow, step_name, context)
                    continue
                if step_name == "adversarial":
                    context = self._run_step(workflow, step_name, context)
                    if _needs_classification_feedback(
                        context,
                        workflow.max_feedback_iterations,
                    ):
                        context["classification_attempt"] += 1
                        context["feedback_iterations"] = (
                            context.get("feedback_iterations", 0) + 1
                        )
                        self._workflows.update(
                            workflow.id,
                            feedback_iterations=context[
                                "feedback_iterations"
                            ],
                        )
                        context = self._run_step(
                            workflow,
                            "classification",
                            context,
                            attempt=context["classification_attempt"],
                        )
                    continue
                context = self._run_step(workflow, step_name, context)

            output = {
                "message": "Alert review workflow completed",
                "final_step": "post_process",
            }
            finished_at = datetime.now(timezone.utc)
            self._workflows.update(
                workflow.id,
                status=WorkflowStatus.SUCCEEDED,
                current_step="post_process",
                output=output,
                finished_at=finished_at,
            )
            self._operations.update(
                workflow.async_operation_id,
                status=AsyncOperationStatus.SUCCEEDED,
                result=output,
            )
            self._alerts.update(workflow.alert_id, status=AlertStatus.CLOSED)
            return {"status": "ok", "workflow_execution_id": str(workflow.id)}
        except Exception as exc:
            error = str(exc)
            finished_at = datetime.now(timezone.utc)
            self._workflows.update(
                workflow.id,
                status=WorkflowStatus.FAILED,
                error=error,
                finished_at=finished_at,
            )
            self._operations.update(
                workflow.async_operation_id,
                status=AsyncOperationStatus.FAILED,
                error=error,
            )
            self._alerts.update(workflow.alert_id, status=AlertStatus.FAILED)
            raise

    def _run_step(
        self,
        workflow: WorkflowExecutionRecord,
        step_name: str,
        context: dict[str, Any],
        attempt: int = 1,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        step = self._steps.create(
            WorkflowStepExecutionRecord(
                id=uuid.uuid4(),
                workflow_execution_id=workflow.id,
                step_name=step_name,
                status=WorkflowStepStatus.RUNNING,
                attempt=attempt,
                input=_step_input(context),
                output=None,
                error=None,
                started_at=now,
                finished_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        self._workflows.update(
            workflow.id,
            status=WorkflowStatus.RUNNING,
            current_step=step_name,
        )

        try:
            output = _execute_placeholder_step(step_name, context)
            finished_at = datetime.now(timezone.utc)
            self._steps.update(
                workflow.id,
                step.id,
                status=WorkflowStepStatus.SUCCEEDED,
                output=output,
                finished_at=finished_at,
            )
            context[step_name] = output
            return context
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            self._steps.update(
                workflow.id,
                step.id,
                status=WorkflowStepStatus.FAILED,
                error=str(exc),
                finished_at=finished_at,
            )
            raise


def _execute_placeholder_step(
    step_name: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    if step_name == "pre_process":
        return {"status": "passed_through"}
    if step_name == "profiling":
        return {
            "transaction_profile": "pending_implementation",
            "user_profile": "pending_implementation",
        }
    if step_name == "classification":
        return {
            "classification": "review",
            "red_flags": [],
            "attempt": context.get("classification_attempt", 1),
        }
    if step_name == "adversarial":
        return {
            "requires_classification_feedback": (
                context.get("classification_attempt", 1) == 1
            ),
            "weak_points": [],
        }
    if step_name == "analyst":
        return {"playbook": "manual_review", "decision": "continue"}
    if step_name == "executor":
        return {"executed_actions": []}
    if step_name == "post_process":
        return {"closed": True}
    raise ValueError(f"Unsupported workflow step: {step_name}")


def _needs_classification_feedback(
    context: dict[str, Any],
    max_feedback_iterations: int,
) -> bool:
    adversarial = context.get("adversarial") or {}
    return bool(
        adversarial.get("requires_classification_feedback")
        and context.get("feedback_iterations", 0) < max_feedback_iterations
    )


def _step_input(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": context["alert_id"],
        "classification_attempt": context.get("classification_attempt", 1),
    }

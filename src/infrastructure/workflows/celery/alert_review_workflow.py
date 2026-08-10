from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertInput,
    AdversarialReviewAlertOutput,
)
from src.application.dtos.analyst_review_alert_dtos import (
    AnalystReviewAlertInput,
    AnalystReviewAlertOutput,
)
from src.application.dtos.classify_alert_dtos import (
    ClassifyAlertInput,
    ClassifyAlertOutput,
)
from src.application.dtos.post_process_alert_dtos import (
    PostProcessAlertInput,
    PostProcessAlertOutput,
)
from src.application.dtos.pre_process_dtos import (
    PreProcessAlertInput,
    PreProcessAlertOutput,
)
from src.application.dtos.profile_alert_dtos import (
    ProfileAlertInput,
    ProfileAlertOutput,
)
from src.application.ports.alert_port import AlertStatus
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.infrastructure.workflows.celery.factories import (
    get_alert_action_dispatcher,
    get_alert_repository,
    get_analyst_decision_documenter,
    get_analyst_escalation_dispatcher,
    get_async_operation_repository,
    get_adversarial_review_alert_use_case,
    get_analyst_review_alert_use_case,
    get_classify_alert_use_case,
    get_post_process_alert_use_case,
    get_pre_process_alert_use_case,
    get_profile_alert_use_case,
    get_workflow_execution_repository,
    get_workflow_step_execution_repository,
)
from src.infrastructure.workflows.queued.queued_status_reporter import (
    QueuedWorkflowStatusReporter,
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
        self._alerts = get_alert_repository()
        self._operations = get_async_operation_repository()
        self._workflows = get_workflow_execution_repository()
        self._steps = get_workflow_step_execution_repository()
        self._escalation = get_analyst_escalation_dispatcher()
        self._documenter = get_analyst_decision_documenter()
        self._status: WorkflowStatusReporter | None = None

    def run(
        self,
        workflow_execution_id: UUID,
        is_final_attempt: bool = True,
    ) -> dict[str, Any]:
        workflow = self._workflows.get(workflow_execution_id)
        if workflow is None:
            return {
                "status": "not_found",
                "workflow_execution_id": str(workflow_execution_id),
            }

        # One reporter per run: a daemon writer thread coalesces the
        # per-step status/progress updates below into DynamoDB writes off
        # the pipeline's hot path. Terminal states (below, in except/else)
        # bypass it and write synchronously so they're durable before the
        # Celery task returns.
        self._status = QueuedWorkflowStatusReporter(self._workflows, self._steps)

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
            "workflow_started_at": workflow.created_at.isoformat(),
            "status_reporter": self._status,
        }

        try:
            for step_name in LINEAR_STEPS:
                if step_name == "adversarial":
                    context = self._run_adversarial_review(workflow, context)
                    continue
                context = self._run_step(workflow, step_name, context)
                if step_name == "analyst":
                    # Fire-and-forget: runs in its own Celery task,
                    # concurrently with the rest of this workflow, so a
                    # slow/failed report never blocks or fails the alert
                    # review itself.
                    self._documenter.dispatch(
                        workflow.alert_id,
                        workflow.id,
                        _context_steps_snapshot(context),
                    )

            post_process: PostProcessAlertOutput = context["post_process"]
            output = {
                "message": "Alert review workflow completed",
                "final_step": "post_process",
                "status": post_process.status,
                "resolution_path": post_process.resolution_path,
                "total_duration_seconds": post_process.total_duration_seconds,
            }
            finished_at = datetime.now(timezone.utc)
            self._status.flush()
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
            self._status.flush()
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
            # Only on the final Celery attempt: autoretry re-runs this
            # whole method from scratch, so escalating on every attempt
            # would fire one escalation per retry instead of one per alert.
            if is_final_attempt:
                if isinstance(exc, AdversarialFeedbackLimitExceededError):
                    self._escalate_to_analyst(workflow, error)
                # pre_process is always the first step; if it never wrote
                # its output to context, that's where the failure happened
                # (either mandatory data missing from the payload, or
                # enrichment fetch exhausted its retries) - escalate that
                # case to an analyst too.
                elif "pre_process" not in context:
                    self._escalate_to_analyst(workflow, error)
            raise
        finally:
            self._status.stop()

    def _escalate_to_analyst(
        self,
        workflow: WorkflowExecutionRecord,
        reason: str,
    ) -> None:
        alert = self._alerts.get(workflow.alert_id)
        event_id = alert.event_id if alert is not None else str(workflow.alert_id)
        self._escalation.dispatch(
            alert_id=workflow.alert_id,
            workflow_execution_id=workflow.id,
            event_id=event_id,
            session_id=None,
            reason=reason,
        )

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
        self._status.report(
            WorkflowStatusUpdate(
                workflow_execution_id=workflow.id,
                status=WorkflowStatus.RUNNING,
                detail={"current_step": step_name},
            )
        )
        context["current_step_id"] = str(step.id)

        try:
            output = _execute_placeholder_step(step_name, context)
            db_output = (
                dataclasses.asdict(output)
                if dataclasses.is_dataclass(output)
                else output
            )
            finished_at = datetime.now(timezone.utc)
            self._status.report(
                WorkflowStatusUpdate(
                    workflow_execution_id=workflow.id,
                    step_name=step_name,
                    step_id=step.id,
                    status=WorkflowStepStatus.SUCCEEDED,
                    detail={"output": db_output, "finished_at": finished_at},
                )
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

    def _run_adversarial_review(
        self,
        workflow: WorkflowExecutionRecord,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._run_step(workflow, "adversarial", context)
        while _needs_classification_feedback(
            context,
            workflow.max_feedback_iterations,
        ):
            context["feedback_iterations"] = (
                context.get("feedback_iterations", 0) + 1
            )
            self._workflows.update(
                workflow.id,
                feedback_iterations=context["feedback_iterations"],
            )
            context["classification_attempt"] += 1
            context = self._run_step(
                workflow,
                "classification",
                context,
                attempt=context["classification_attempt"],
            )
            context = self._run_step(workflow, "adversarial", context)

        adversarial: AdversarialReviewAlertOutput = context["adversarial"]
        if (
            adversarial.requires_classification_feedback
            and context.get("feedback_iterations", 0)
            >= workflow.max_feedback_iterations
        ):
            raise AdversarialFeedbackLimitExceededError(
                f"Adversarial review still flagged issues after "
                f"{context['feedback_iterations']} feedback loop(s) back to "
                f"classification: {adversarial.feedback}"
            )
        return context


class AdversarialFeedbackLimitExceededError(Exception):
    """Raised when adversarial review keeps rejecting classification past
    the workflow's allowed feedback loop-backs, so the alert must escalate
    to a human analyst instead of looping forever."""


def _step_reporting_ids(context: dict[str, Any]) -> tuple[UUID | None, UUID | None]:
    status_reporter = context.get("status_reporter")
    if status_reporter is None:
        return None, None
    step_id = context.get("current_step_id")
    return (
        UUID(context["workflow_execution_id"]),
        UUID(step_id) if step_id else None,
    )


def _run_pre_process(context: dict[str, Any]) -> PreProcessAlertOutput:
    payload = (context.get("input") or {}).get("alert_payload") or {}
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_pre_process_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    return use_case.execute(
        PreProcessAlertInput(
            alert_id=UUID(context["alert_id"]),
            payload=payload,
        )
    )


def _run_profiling(context: dict[str, Any]) -> ProfileAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_profile_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    return use_case.execute(
        ProfileAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
        )
    )


def _run_classification(context: dict[str, Any]) -> ClassifyAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_classify_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    return use_case.execute(
        ClassifyAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
            profile=context["profiling"],
        )
    )


def _run_adversarial(context: dict[str, Any]) -> AdversarialReviewAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_adversarial_review_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    return use_case.execute(
        AdversarialReviewAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
            profile=context["profiling"],
            classification=context["classification"],
        )
    )


def _run_analyst(context: dict[str, Any]) -> AnalystReviewAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_analyst_review_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    return use_case.execute(
        AnalystReviewAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
            profile=context["profiling"],
            classification=context["classification"],
        )
    )


def _run_executor(context: dict[str, Any]) -> dict[str, Any]:
    analyst: AnalystReviewAlertOutput = context["analyst"]
    decision = analyst.decision
    alert_id = UUID(context["alert_id"])

    if decision == "pass":
        return {
            "executed_action": "none",
            "detail": "Analyst decision was pass - no action required.",
        }

    if decision == "scale_to_analyst":
        alert = get_alert_repository().get(alert_id)
        event_id = alert.event_id if alert is not None else str(alert_id)
        ref = get_analyst_escalation_dispatcher().dispatch(
            alert_id=alert_id,
            workflow_execution_id=UUID(context["workflow_execution_id"]),
            event_id=event_id,
            session_id=None,
            reason=analyst.reasoning,
        )
        return {
            "executed_action": decision,
            "dispatch_backend": ref.backend,
            "dispatch_external_id": ref.external_id,
        }

    if decision in ("block", "bidi", "voicebot"):
        ref = get_alert_action_dispatcher().dispatch(decision, alert_id)
        return {
            "executed_action": decision,
            "dispatch_backend": ref.backend,
            "dispatch_external_id": ref.external_id,
        }

    raise ValueError(f"Unsupported analyst decision: {decision}")


def _run_post_process(context: dict[str, Any]) -> PostProcessAlertOutput:
    analyst: AnalystReviewAlertOutput = context["analyst"]
    use_case = get_post_process_alert_use_case()
    return use_case.execute(
        PostProcessAlertInput(
            alert_id=UUID(context["alert_id"]),
            workflow_started_at=datetime.fromisoformat(
                context["workflow_started_at"]
            ),
            resolution_path=analyst.decision,
        )
    )


def _execute_placeholder_step(
    step_name: str,
    context: dict[str, Any],
) -> Any:
    if step_name == "pre_process":
        return _run_pre_process(context)
    if step_name == "profiling":
        return _run_profiling(context)
    if step_name == "classification":
        return _run_classification(context)
    if step_name == "adversarial":
        return _run_adversarial(context)
    if step_name == "analyst":
        return _run_analyst(context)
    if step_name == "executor":
        return _run_executor(context)
    if step_name == "post_process":
        return _run_post_process(context)
    raise ValueError(f"Unsupported workflow step: {step_name}")


_DOCUMENTED_STEPS = (
    "pre_process",
    "profiling",
    "classification",
    "adversarial",
    "analyst",
)


def _context_steps_snapshot(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for step_name in _DOCUMENTED_STEPS:
        output = context.get(step_name)
        if output is None:
            continue
        snapshot[step_name] = (
            dataclasses.asdict(output) if dataclasses.is_dataclass(output) else output
        )
    return snapshot


def _needs_classification_feedback(
    context: dict[str, Any],
    max_feedback_iterations: int,
) -> bool:
    adversarial: AdversarialReviewAlertOutput | None = context.get("adversarial")
    return bool(
        adversarial is not None
        and adversarial.requires_classification_feedback
        and context.get("feedback_iterations", 0) < max_feedback_iterations
    )


def _step_input(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": context["alert_id"],
        "classification_attempt": context.get("classification_attempt", 1),
    }

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
from src.application.ports.configuration_port import (
    ClassificationConfig,
    ProfilingStrategyKey,
    SegmentSettings,
    VectorStoreTool,
)
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
    get_configuration_repository,
    get_post_process_alert_use_case,
    get_pre_process_alert_use_case,
    get_profile_alert_use_case,
    get_workflow_execution_repository,
    get_workflow_step_execution_repository,
)
from src.application.use_cases.alerts.resolve_alert_segment import (
    ResolveAlertSegmentUseCase,
)
from src.application.use_cases.test_runs.dataset_sampling import (
    MARCACION_FIELD,
    TIPO_FIELD,
)
from src.domain.configurations.exceptions import ConfigurationNotFoundError
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
                if step_name == "pre_process":
                    context = _resolve_segment(context)
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
            # AdversarialFeedbackLimitExceededError is excluded from Celery
            # autoretry (see tasks.py), so it's terminal on this one raise
            # regardless of is_final_attempt - escalate every time.
            if isinstance(exc, AdversarialFeedbackLimitExceededError):
                self._escalate_to_analyst(workflow, error)
            # Only on the final Celery attempt: autoretry re-runs this
            # whole method from scratch, so escalating on every attempt
            # would fire one escalation per retry instead of one per alert.
            # pre_process is always the first step; if it never wrote its
            # output to context, that's where the failure happened (either
            # mandatory data missing from the payload, or enrichment fetch
            # exhausted its retries) - escalate that case to an analyst too.
            elif is_final_attempt and "pre_process" not in context:
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
            # Must go through the queue, not a direct self._steps.update():
            # a progress report from mid-step (e.g. profile_alert's
            # _report_progress) may still be pending/in-flight for this same
            # (workflow, step) key. update() is read-modify-write, not
            # atomic - a direct write here can lose the race to that stale
            # write landing afterward and revert status back to RUNNING
            # while leaving this error text in place (it only overwrites
            # the fields it sets). Routing through report() lets the
            # single-writer queue coalesce/order them correctly instead.
            self._status.report(
                WorkflowStatusUpdate(
                    workflow_execution_id=workflow.id,
                    step_name=step_name,
                    step_id=step.id,
                    status=WorkflowStepStatus.FAILED,
                    detail={"error": str(exc), "finished_at": finished_at},
                )
            )
            self._status.flush()
            raise

    def _run_adversarial_review(
        self,
        workflow: WorkflowExecutionRecord,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._run_step(workflow, "adversarial", context)
        effective_max = _effective_max_feedback_iterations(workflow, context)
        while _needs_classification_feedback(
            context,
            effective_max,
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
            >= effective_max
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


def _step_overrides(
    context: dict[str, Any], step_name: str
) -> dict[str, str | None]:
    # A test run stashes its TestRunConfig (asdict'd) under
    # input["config_overrides"] - {} for a normal (non-test) alert, so
    # these always resolve to "use the config-driven default".
    config_overrides = (context.get("input") or {}).get("config_overrides") or {}
    return {
        "system_prompt": (config_overrides.get("prompt_overrides") or {}).get(
            step_name
        ),
        "model": (config_overrides.get("model_overrides") or {}).get(step_name),
    }


_VECTOR_TOOL_MAP = {
    VectorStoreTool.SIMILAR_CASE: "get_similar_frauds",
    VectorStoreTool.TAXONOMIA: "get_similar_taxonomy",
    VectorStoreTool.MODUS_OPERANDI: "get_similar_modus_operandi",
    # RED_FLAG / YELLOW_FLAG: no backing tool yet, silently dropped.
}

_PROFILING_STRATEGY_OPERATION_MAP = {
    ProfilingStrategyKey.USUARIO: "user_profile",
    ProfilingStrategyKey.TRANSACCION: "transaction_profile",
    ProfilingStrategyKey.TRANSACCIONAL: "transactional_profile",
}


def _segment_tool_kwargs(classification_cfg: ClassificationConfig) -> dict[str, Any]:
    if not classification_cfg.vector_store_tools:  # empty == no restriction
        return {}
    return {
        "enabled_tools": {
            _VECTOR_TOOL_MAP[t]
            for t in classification_cfg.vector_store_tools
            if t in _VECTOR_TOOL_MAP
        }
    }


def _run_profiling(context: dict[str, Any]) -> ProfileAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, "profiling")
    segment_kwargs: dict[str, Any] = {}
    if not overrides.get("system_prompt"):
        segment = _active_segment(context)
        if segment is not None:
            extra_instructions = {
                _PROFILING_STRATEGY_OPERATION_MAP[s.key]: s.main_prompt
                for s in segment.agent.profiling.strategies
                if s.main_prompt and s.key in _PROFILING_STRATEGY_OPERATION_MAP
            }
            if extra_instructions:
                segment_kwargs["extra_instructions"] = extra_instructions
    use_case = get_profile_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        **overrides,
        **segment_kwargs,
    )
    return use_case.execute(
        ProfileAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
        )
    )


def _resolve_configuration(context: dict[str, Any]):
    # A test run can pin an exact (possibly inactive) ConfigurationRecord
    # via configuration_ref, instead of the implicit get_active() - see
    # ConfigurationRef (configuration_port.py) and TestRunConfig
    # (test_run_port.py). Unlike the no-ref path below, an explicit ref
    # that doesn't resolve must raise: silently falling back to whatever
    # is currently active would corrupt the meaning of the test, and the
    # caller (the outer Celery task) is expected to surface this as a
    # failed workflow, not a misleadingly "successful" one run against
    # the wrong config.
    ref = (context.get("input") or {}).get("configuration_ref")
    repo = get_configuration_repository()
    if ref:
        configuration_id = ref["configuration_id"]
        version = ref.get("version")
        config = (
            repo.get(configuration_id, version)
            if version is not None
            else repo.get_latest_version(configuration_id)
        )
        if config is None:
            raise ConfigurationNotFoundError(configuration_id, version)
        return config
    try:
        return repo.get_active()
    except Exception:
        return None


def _resolve_segment(context: dict[str, Any]) -> dict[str, Any]:
    # Context enrichment, not a persisted workflow step - must fail safe to
    # "no segment" (None) and never break existing behavior when there's no
    # active configuration or nothing matches. The one exception is an
    # explicit configuration_ref that fails to resolve - see
    # _resolve_configuration.
    config = _resolve_configuration(context)
    context["active_configuration"] = config
    context["segment_code"] = None
    if config is None:
        return context
    try:
        pre_process: PreProcessAlertOutput = context["pre_process"]
        context["segment_code"] = ResolveAlertSegmentUseCase().execute(
            mandatory_fields=pre_process.mandatory_fields,
            segments=config.segments,
        )
    except Exception:
        context["segment_code"] = None
    return context


def _active_segment(context: dict[str, Any]) -> SegmentSettings | None:
    config = context.get("active_configuration")
    code = context.get("segment_code")
    if config is None or code is None:
        return None
    segment = config.segments.get(code)
    return segment if segment is not None and segment.enabled else None


def _effective_max_feedback_iterations(
    workflow: WorkflowExecutionRecord, context: dict[str, Any]
) -> int:
    segment = _active_segment(context)
    if segment is not None:
        return segment.agent.adversarial.max_cycles
    return workflow.max_feedback_iterations


def _run_classification(context: dict[str, Any]) -> ClassifyAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, "classification")
    segment_kwargs: dict[str, Any] = {}
    if not overrides.get("system_prompt"):
        segment = _active_segment(context)
        if segment is not None:
            classification_cfg = segment.agent.classification
            if classification_cfg.prompt:
                segment_kwargs["extra_instructions"] = classification_cfg.prompt
            segment_kwargs.update(_segment_tool_kwargs(classification_cfg))
    use_case = get_classify_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        **overrides,
        **segment_kwargs,
    )
    alert_payload = (context.get("input") or {}).get("alert_payload") or {}
    return use_case.execute(
        ClassifyAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
            profile=context["profiling"],
            expected_classification=alert_payload.get(MARCACION_FIELD),
            ground_truth_tipo=alert_payload.get(TIPO_FIELD),
        )
    )


def _run_adversarial(context: dict[str, Any]) -> AdversarialReviewAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, "adversarial")
    segment_kwargs: dict[str, Any] = {}
    if not overrides.get("system_prompt"):
        segment = _active_segment(context)
        if segment is not None:
            if segment.agent.adversarial.prompt:
                segment_kwargs["extra_instructions"] = segment.agent.adversarial.prompt
            # No tool picker of its own by product design - reuses
            # Classification's selection.
            segment_kwargs.update(_segment_tool_kwargs(segment.agent.classification))
    use_case = get_adversarial_review_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        **overrides,
        **segment_kwargs,
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
        **_step_overrides(context, "analyst"),
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

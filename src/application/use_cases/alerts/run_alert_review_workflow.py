from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertOutput,
)
from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.analyst_review_alert_dtos import AnalystReviewAlertOutput
from src.application.dtos.discard_alert_dtos import DiscardAlertInput
from src.application.dtos.evaluate_deterministic_rules_dtos import (
    DeterministicRuleMatch,
)
from src.application.dtos.post_process_alert_dtos import PostProcessAlertOutput
from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.application.dtos.run_alert_review_workflow_dtos import (
    RunAlertReviewWorkflowOutput,
)
from src.application.dtos.technical_metrics_dtos import RecordWorkflowStepMetricsInput
from src.application.dtos.workflow_run_state import WorkflowRunState
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.alert_review_step_executor_port import (
    AlertReviewStepExecutor,
)
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.analyst_decision_documenter_port import (
    AnalystDecisionDocumenter,
)
from src.application.ports.analyst_escalation_port import AnalystEscalationDispatcher
from src.application.ports.async_operation_port import (
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import (
    ATTR_ALERT_ID,
    ATTR_WORKFLOW_ATTEMPT,
    ATTR_WORKFLOW_EXECUTION_ID,
    ATTR_WORKFLOW_OUTCOME,
    ATTR_WORKFLOW_STEP,
    ATTR_WORKFLOW_STEP_ID,
    WORKFLOW_TOTAL_STEP,
    MonitoringPort,
    span_dimension_attributes,
)
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.ports.reasoning_evaluation_dispatcher_port import (
    ReasoningEvaluationDispatcher,
)
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.application.ports.workflow_step_execution_port import (
    WorkflowStepExecutionRepository,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.application.use_cases.alerts.agent_gate import agent_off_skip_reason
from src.application.use_cases.alerts.alert_review_policy import (
    LINEAR_STEPS,
    context_steps_snapshot,
    effective_max_detector_feedback_iterations,
    effective_max_feedback_iterations,
    needs_classification_feedback,
    needs_detector_feedback,
    output_as_dict,
    relative_value,
    step_input,
)
from src.application.use_cases.alerts.discard_alert import DiscardAlertUseCase
from src.application.use_cases.alerts.raw_payload import RawAlertPayloadLoader
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.application.use_cases.metrics.record_workflow_step_metrics import (
    RecordWorkflowStepMetrics,
)
from src.domain.alerts.entities import (
    AdversarialDecision,
    AlertOrigin,
    AlertStatus,
)
from src.domain.alerts.exceptions import AdversarialFeedbackLimitExceededError
from src.domain.workflows.entities import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)

logger = logging.getLogger(__name__)


class RunAlertReviewWorkflowUseCase:
    """Orchestrates one attempt of the fraud-alert review workflow.

    Owns step sequencing, status transitions, the adversarial feedback-loop
    limits, escalation on failure and terminal outcomes. What each step
    actually does is delegated to an ``AlertReviewStepExecutor``; delivery
    concerns (task retry, serialisation) stay with the caller.
    """

    def __init__(
        self,
        *,
        alerts: AlertRepository,
        operations: AsyncOperationRepository,
        workflows: WorkflowExecutionRepository,
        steps: WorkflowStepExecutionRepository,
        step_executor: AlertReviewStepExecutor,
        status_reporter_factory: Callable[[], WorkflowStatusReporter],
        escalation: AnalystEscalationDispatcher,
        documenter: AnalystDecisionDocumenter,
        reasoning_evaluation: ReasoningEvaluationDispatcher,
        operational_settings: OperationalSettingsRepository,
        monitoring: MonitoringPort,
        discard_alert: DiscardAlertUseCase,
        record_metrics_event: RecordAlertMetricsEvent,
        record_step_metrics: RecordWorkflowStepMetrics,
        step_models: Callable[[dict[str, str]], dict[str, str]],
        raw_payload_loader_factory: Callable[[], RawAlertPayloadLoader],
        alert_schemas_factory: Callable[[], AlertSchemaRepository],
        alert_object_storage_factory: Callable[[], ObjectStoragePort],
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._alerts = alerts
        self._operations = operations
        self._workflows = workflows
        self._steps = steps
        self._executor = step_executor
        self._status_reporter_factory = status_reporter_factory
        self._escalation = escalation
        self._documenter = documenter
        self._reasoning_evaluation = reasoning_evaluation
        self._operational_settings = operational_settings
        self._monitoring = monitoring
        self._discard_alert = discard_alert
        self._record_metrics_event = record_metrics_event
        self._record_step_metrics_use_case = record_step_metrics
        self._step_models = step_models
        self._raw_payload_loader_factory = raw_payload_loader_factory
        # Resolved on first use: only alerts persisted with a raw payload
        # ref write per-step agent output, so most runs never need them.
        self._alert_schemas_factory = alert_schemas_factory
        self._alert_object_storage_factory = alert_object_storage_factory
        self._status: WorkflowStatusReporter | None = None
        self._workflow_span: MonitoringSpan | None = None
        # T2: the alert's known dimensions (aria.channel, aria.segment, ...)
        # from its metrics snapshot - refreshed after every metrics event and
        # copied onto each step span.
        self._dimensions: dict[str, str] = {}
        self._raw_payloads: RawAlertPayloadLoader | None = None
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        workflow_execution_id: UUID,
        is_final_attempt: bool = True,
    ) -> RunAlertReviewWorkflowOutput:
        workflow = self._workflows.get(workflow_execution_id)
        if workflow is None:
            return RunAlertReviewWorkflowOutput(
                status="not_found",
                workflow_execution_id=str(workflow_execution_id),
            )

        started = time.perf_counter()
        alert = self._alerts.get(workflow.alert_id)
        self._dimensions = span_dimension_attributes(
            alert.metrics if alert is not None else None
        )
        span = self._monitoring.start_workflow(
            "alert_review_workflow",
            workflow.id,
            metadata={
                ATTR_ALERT_ID: str(workflow.alert_id),
                ATTR_WORKFLOW_EXECUTION_ID: str(workflow.id),
                **self._dimensions,
            },
        )
        self._workflow_span = span
        error: str | None = None
        try:
            return self._run(workflow, is_final_attempt)
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            # Outcome = the alert's final status for this attempt
            # (CLOSED/ESCALATED/FAILED/SKIPPED).
            alert = self._alerts.get(workflow.alert_id)
            outcome = str(alert.status) if alert is not None else "UNKNOWN"
            span.write_operation_metas(
                {**self._dimensions, ATTR_WORKFLOW_OUTCOME: outcome}
            )
            span.finish(error)
            self._workflow_span = None
            self._monitoring.record_workflow_duration(
                WORKFLOW_TOTAL_STEP, outcome, time.perf_counter() - started
            )

    def _run(
        self,
        workflow: WorkflowExecutionRecord,
        is_final_attempt: bool,
    ) -> RunAlertReviewWorkflowOutput:
        alert = self._alerts.get(workflow.alert_id)
        origin = AlertOrigin((workflow.input or {}).get("origin") or "manual")
        skip_reason = agent_off_skip_reason(origin, self._operational_settings.get())
        if skip_reason is not None:
            return self._skip(workflow, origin, skip_reason)

        # One reporter per run: a daemon writer thread coalesces the
        # per-step status/progress updates below into DynamoDB writes off
        # the pipeline's hot path. Terminal states (below, in except/else)
        # bypass it and write synchronously so they're durable before the
        # task returns.
        self._status = self._status_reporter_factory()

        self._operations.update(
            workflow.async_operation_id,
            status=AsyncOperationStatus.RUNNING,
        )
        self._workflows.update(
            workflow.id,
            status=WorkflowStatus.RUNNING,
        )

        context: WorkflowRunState = {
            "workflow_execution_id": str(workflow.id),
            "alert_id": str(workflow.alert_id),
            "async_operation_id": str(workflow.async_operation_id),
            "input": workflow.input,
            "classification_attempt": 1,
            "detector_attempt": 1,
            "workflow_started_at": workflow.created_at.isoformat(),
            "status_reporter": self._status,
            "raw_payload": self._load_raw_payload(alert),
        }

        try:
            discarded = False
            # Populated when Detector gates the alert to "not_fraud" (see
            # the "detector" handling below) - every step named here is
            # skipped for the rest of this run, same effect as never
            # having been in LINEAR_STEPS for this particular alert.
            skip_steps: set[str] = set()
            for step_name in LINEAR_STEPS:
                if step_name in skip_steps:
                    continue
                if step_name == "adversarial":
                    context = self._run_adversarial_review(workflow, context)
                    continue
                if step_name == "detector_adversarial":
                    context = self._run_detector_adversarial_review(workflow, context)
                    review = context["detector_adversarial"]
                    if review.decision != AdversarialDecision.HANDLE_BY_ARIA:
                        context["analyst"] = AnalystReviewAlertOutput(
                            decision=review.decision.value,
                            reasoning=review.reasoning,
                        )
                        skip_steps |= {"classification", "adversarial", "analyst"}
                    continue
                context = self._run_step(workflow, step_name, context)
                context = self._executor.enrich(step_name, context)
                if step_name == "pre_process":
                    self._persist_schema_comparison(workflow, context)
                    config = context.get("active_configuration")
                    if config is not None:
                        self._alerts.update(
                            workflow.alert_id,
                            configuration_id=config.configuration_id,
                            configuration_version=config.version,
                        )
                    pre_processed: PreProcessAlertOutput = context["pre_process"]
                    # Persist the canonical schema result before recording its
                    # metrics event. The recorder reloads the alert to derive
                    # channel/subchannel/amount from schema roles; recording
                    # first leaves the CREATED snapshot in the provisional
                    # unknown bucket because it still sees the pre-intake alert.
                    self._persist_pre_process(workflow, context)
                    self._record_metrics(
                        workflow,
                        AlertMetricsEventType.PRE_PROCESSED,
                        roles=pre_processed.roles,
                        segment=context.get("segment_code"),
                        configuration_id=(
                            config.configuration_id if config is not None else None
                        ),
                    )
                if step_name == "deterministic":
                    match: DeterministicRuleMatch = context["deterministic"]
                    if match.matched:
                        # Terminal for this run - skip profiling through
                        # post_process entirely. See DiscardAlertUseCase's
                        # own docstring for why this only logs today.
                        self._discard_alert.execute(
                            DiscardAlertInput(
                                alert_id=workflow.alert_id,
                                reason=(
                                    f"Deterministic rule {match.rule_id!r} "
                                    f"matched on {match.variable!r}."
                                ),
                                rule_id=match.rule_id,
                                decision=match.decision,
                                aric_action=match.aric_action,
                            )
                        )
                        discarded = True
                        break
                if step_name == "analyst":
                    # Fire-and-forget: runs in its own task, concurrently
                    # with the rest of this workflow, so a slow/failed
                    # report never blocks or fails the alert review itself.
                    if origin not in {
                        AlertOrigin.TEST_RUN,
                        AlertOrigin.OPTIMIZER_EVALUATION,
                    }:
                        self._documenter.dispatch(
                            workflow.alert_id,
                            workflow.id,
                            context_steps_snapshot(context),
                        )

            if discarded:
                match = context["deterministic"]
                duration = (self._clock.now() - workflow.created_at).total_seconds()
                output = {
                    "message": "Alert discarded by deterministic rule match",
                    "final_step": "deterministic",
                    "status": "discarded",
                    "resolution_path": "discarded_deterministic",
                    "total_duration_seconds": duration,
                }
                current_step = "deterministic"
            else:
                post_process: PostProcessAlertOutput = context["post_process"]
                output = {
                    "message": "Alert review workflow completed",
                    "final_step": "post_process",
                    "status": post_process.status,
                    "resolution_path": post_process.resolution_path,
                    "total_duration_seconds": post_process.total_duration_seconds,
                }
                current_step = "post_process"
            finished_at = self._clock.now()
            self._status.flush()
            self._workflows.update(
                workflow.id,
                status=WorkflowStatus.SUCCEEDED,
                current_step=current_step,
                output=output,
                finished_at=finished_at,
            )
            self._operations.update(
                workflow.async_operation_id,
                status=AsyncOperationStatus.SUCCEEDED,
                result=output,
            )
            executed = context.get("executor") or {}
            final_status = (
                AlertStatus.ESCALATED
                if executed.get("executed_action") == "scale_to_analyst"
                else AlertStatus.CLOSED
            )
            # Waits in the analyst queue until a human resolves it.
            self._alerts.update(workflow.alert_id, status=final_status)
            self._record_metrics(
                workflow,
                AlertMetricsEventType.WORKFLOW_FINISHED,
                status=final_status,
                executed_action=(
                    "discarded" if discarded else executed.get("executed_action")
                ),
            )
            self._record_step_metrics(workflow)
            if not discarded and origin not in {
                AlertOrigin.TEST_RUN,
                AlertOrigin.OPTIMIZER_EVALUATION,
            }:
                self._dispatch_reasoning_evaluation(workflow)
            return RunAlertReviewWorkflowOutput(
                status="ok", workflow_execution_id=str(workflow.id)
            )
        except Exception as exc:
            error = str(exc)
            finished_at = self._clock.now()
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
            self._record_metrics(
                workflow,
                AlertMetricsEventType.WORKFLOW_FINISHED,
                status=AlertStatus.FAILED,
            )
            # Test runs are isolated from operational analyst escalation.
            if origin in {AlertOrigin.TEST_RUN, AlertOrigin.OPTIMIZER_EVALUATION}:
                pass
            # AdversarialFeedbackLimitExceededError is excluded from the
            # delivery layer's automatic retry, so it's terminal on this one
            # raise regardless of is_final_attempt - escalate every time.
            elif isinstance(exc, AdversarialFeedbackLimitExceededError):
                self._escalate_to_analyst(workflow, error)
            # Only on the final attempt: a retry re-runs this whole method
            # from scratch, so escalating on every attempt would fire one
            # escalation per retry instead of one per alert.
            # pre_process is always the first step; if it never wrote its
            # output to context, that's where the failure happened (either
            # mandatory data missing from the payload, or enrichment fetch
            # exhausted its retries) - escalate that case to an analyst too.
            elif is_final_attempt and "pre_process" not in context:
                self._escalate_to_analyst(workflow, error)
            # After the escalation, so the steps carry the alert's final
            # status for this attempt. Steps of an attempt that will be
            # retried are counted now (they ran); the next attempt's call
            # skips them via their apply_once markers.
            self._record_step_metrics(workflow)
            raise
        finally:
            self._status.stop()

    def _skip(
        self,
        workflow: WorkflowExecutionRecord,
        origin: AlertOrigin,
        reason: str,
    ) -> RunAlertReviewWorkflowOutput:
        logger.warning(
            "Alert skipped: reason=%r alert_id=%s origin=%s workflow_execution_id=%s",
            reason,
            workflow.alert_id,
            origin.value,
            workflow.id,
        )
        output = {
            "message": "Alert skipped: the agent is switched off",
            "final_step": None,
            "status": "skipped",
            "resolution_path": "skipped_agent_disabled",
            "reason": reason,
            "origin": origin.value,
            "total_duration_seconds": 0,
        }
        now = self._clock.now()
        self._workflows.update(
            workflow.id,
            status=WorkflowStatus.SUCCEEDED,
            output=output,
            finished_at=now,
        )
        self._operations.update(
            workflow.async_operation_id,
            status=AsyncOperationStatus.SUCCEEDED,
            result=output,
        )
        self._alerts.update(workflow.alert_id, status=AlertStatus.SKIPPED)
        self._record_metrics(
            workflow,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.SKIPPED,
        )
        return RunAlertReviewWorkflowOutput(
            status="skipped", workflow_execution_id=str(workflow.id)
        )

    def _record_metrics(
        self,
        workflow: WorkflowExecutionRecord,
        event_type: AlertMetricsEventType,
        **fields: Any,
    ) -> None:
        if (
            AlertOrigin((workflow.input or {}).get("origin") or "manual")
            == AlertOrigin.OPTIMIZER_EVALUATION
        ):
            return
        # Best effort: a metrics failure must never fail (and so retry) the
        # alert review. Re-recording the same event on a retry is a no-op
        # (RecordAlertMetricsEvent compares snapshots), and the daily
        # reconciliation repairs anything lost here.
        try:
            snapshot = self._record_metrics_event.execute(
                RecordAlertMetricsEventInput(
                    alert_id=workflow.alert_id, event_type=event_type, **fields
                )
            )
            if snapshot is not None:
                self._dimensions.update(span_dimension_attributes(snapshot))
                if self._workflow_span is not None:
                    self._workflow_span.write_operation_metas(self._dimensions)
        except Exception:
            logger.exception(
                "Metrics event %s failed for alert %s",
                event_type.value,
                workflow.alert_id,
            )

    def _record_step_metrics(self, workflow: WorkflowExecutionRecord) -> None:
        if (
            AlertOrigin((workflow.input or {}).get("origin") or "manual")
            == AlertOrigin.OPTIMIZER_EVALUATION
        ):
            return
        # R8 technical rollups from the run's persisted step records (call
        # after self._status.flush()). Best effort like _record_metrics:
        # exactly-once per step execution is RecordWorkflowStepMetrics'
        # job, so calling it again on a retry/escalation is harmless.
        try:
            config_overrides = (workflow.input or {}).get("config_overrides") or {}
            self._record_step_metrics_use_case.execute(
                RecordWorkflowStepMetricsInput(
                    alert_id=workflow.alert_id,
                    workflow_execution_id=workflow.id,
                    step_models=self._step_models(
                        config_overrides.get("model_overrides") or {}
                    ),
                )
            )
        except Exception:
            logger.exception("Step metrics failed for alert %s", workflow.alert_id)

    def _dispatch_reasoning_evaluation(self, workflow: WorkflowExecutionRecord) -> None:
        # Fire-and-forget announcement that this alert finished. Whether it is
        # judged (sampling, origin) and how that goes is the evaluator's own
        # business, on its own queue and with its own state: the alert is already
        # resolved, and nothing here waits for or depends on the evaluator.
        try:
            self._reasoning_evaluation.dispatch(workflow.alert_id, workflow.id)
        except Exception:
            logger.exception(
                "Reasoning evaluation announcement failed for alert %s",
                workflow.alert_id,
            )

    def _escalate_to_analyst(
        self,
        workflow: WorkflowExecutionRecord,
        reason: str,
    ) -> None:
        # A failed review that goes to a human still lands in the analyst
        # queue, same as a normal scale_to_analyst decision.
        self._alerts.update(workflow.alert_id, status=AlertStatus.ESCALATED)
        self._record_metrics(
            workflow,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.ESCALATED,
            executed_action="scale_to_analyst",
        )
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
        context: WorkflowRunState,
        attempt: int = 1,
    ) -> WorkflowRunState:
        assert self._status is not None
        now = self._clock.now()
        step = self._steps.create(
            WorkflowStepExecutionRecord(
                id=self._id_generator.new_id(),
                workflow_execution_id=workflow.id,
                step_name=step_name,
                status=WorkflowStepStatus.RUNNING,
                attempt=attempt,
                input=step_input(context),
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

        step_started = time.perf_counter()
        step_span = self._monitoring.start(
            f"alert_review_workflow.{step_name}",
            "workflow.step",
            metadata={
                ATTR_ALERT_ID: str(workflow.alert_id),
                ATTR_WORKFLOW_STEP: step_name,
                ATTR_WORKFLOW_STEP_ID: str(step.id),
                ATTR_WORKFLOW_ATTEMPT: attempt,
                **self._dimensions,
            },
        )
        try:
            output = self._executor.execute(step_name, context)
            db_output = output_as_dict(output)
            finished_at = self._clock.now()
            self._status.report(
                WorkflowStatusUpdate(
                    workflow_execution_id=workflow.id,
                    step_name=step_name,
                    step_id=step.id,
                    status=WorkflowStepStatus.SUCCEEDED,
                    detail={"output": db_output, "finished_at": finished_at},
                )
            )
            # Step names are runtime values from LINEAR_STEPS; their outputs
            # share one state record but have step-specific value types.
            context[step_name] = output  # type: ignore[literal-required]
            self._persist_agent_step(workflow, context, step_name, db_output)
            self._finish_step_span(
                step_span, step_name, WorkflowStepStatus.SUCCEEDED, step_started
            )
            return context
        except Exception as exc:
            self._finish_step_span(
                step_span, step_name, WorkflowStepStatus.FAILED, step_started, str(exc)
            )
            finished_at = self._clock.now()
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

    def _persist_pre_process(
        self, workflow: WorkflowExecutionRecord, context: WorkflowRunState
    ) -> None:
        result: PreProcessAlertOutput = context["pre_process"]
        config = context.get("active_configuration")
        self._alerts.update(
            workflow.alert_id,
            schema_version=result.schema_version,
            input=result.input,
            labels=result.labels,
            history_prev_alerta=result.history,
            configuration_id=config.configuration_id if config is not None else None,
            configuration_version=config.version if config is not None else None,
        )

    def _persist_schema_comparison(
        self, workflow: WorkflowExecutionRecord, context: WorkflowRunState
    ) -> None:
        comparison = context.get("schema_comparison")
        if comparison is not None:
            self._workflows.update(workflow.id, schema_comparison=comparison)

    def _persist_agent_step(
        self,
        workflow: WorkflowExecutionRecord,
        context: WorkflowRunState,
        step_name: str,
        db_output: Any,
    ) -> None:
        alert = self._alerts.get(workflow.alert_id)
        if alert is None or alert.raw_payload_ref is None:
            return
        schema = self._alert_schemas_factory().get_active()
        if schema is None:
            return
        summary = dict(alert.agent_output)
        for field in schema.fields:
            if field.data_source.value != "aria" or not field.field_ds_loc:
                continue
            value = relative_value(db_output, field.field_ds_loc)
            if value is not None:
                summary[field.field] = value
        current = context.setdefault("agent_outputs", {})
        current[step_name] = db_output
        ref = self._alert_object_storage_factory().put_text(
            f"alerts/{workflow.alert_id}/agent-output.json",
            json.dumps(current, ensure_ascii=False, default=str),
            "application/json",
        )
        self._alerts.update(
            workflow.alert_id,
            agent_output=summary,
            agent_output_ref=ref,
        )

    def _load_raw_payload(self, alert: Any) -> dict[str, Any]:
        if alert is None:
            return {}
        if alert.raw_payload_ref is None:
            # Hand-written workflow fixtures use canonical input directly;
            # persisted alerts always have raw_payload_ref.
            return alert.input
        if self._raw_payloads is None:
            self._raw_payloads = self._raw_payload_loader_factory()
        return self._raw_payloads.load(alert)

    def _finish_step_span(
        self,
        span: MonitoringSpan,
        step_name: str,
        status: WorkflowStepStatus,
        started: float,
        error: str | None = None,
    ) -> None:
        span.finish(error)
        self._monitoring.record_workflow_duration(
            step_name, str(status), time.perf_counter() - started
        )

    def _run_adversarial_review(
        self,
        workflow: WorkflowExecutionRecord,
        context: WorkflowRunState,
    ) -> WorkflowRunState:
        context = self._run_step(workflow, "adversarial", context)
        effective_max = effective_max_feedback_iterations(workflow, context)
        while needs_classification_feedback(context, effective_max):
            context["feedback_iterations"] = context.get("feedback_iterations", 0) + 1
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
            and context.get("feedback_iterations", 0) >= effective_max
        ):
            raise AdversarialFeedbackLimitExceededError(
                f"Adversarial review "
                f"{AdversarialFeedbackLimitExceededError.MESSAGE_MARKER} "
                f"{context.get('feedback_iterations', 0)} feedback loop(s) back to "
                f"classification: {adversarial.feedback}"
            )
        return context

    def _run_detector_adversarial_review(
        self,
        workflow: WorkflowExecutionRecord,
        context: WorkflowRunState,
    ) -> WorkflowRunState:
        # Twin of _run_adversarial_review, for the Detector/Adversarial
        # (detector) pair instead of Clasificación/Adversarial
        # (clasificador) - kept as a separate method rather than a
        # generalized/parameterized one to avoid touching the existing,
        # already-covered classification<->adversarial loop while adding
        # this one. Deliberately does NOT persist its iteration count onto
        # WorkflowExecutionRecord.feedback_iterations - that field already
        # means "classification feedback loops" (see the other loop
        # above); this loop's count only needs to exist for the duration
        # of this run, to bound its own retries.
        context = self._run_step(workflow, "detector_adversarial", context)
        effective_max = effective_max_detector_feedback_iterations(workflow, context)
        while needs_detector_feedback(context, effective_max):
            context["detector_feedback_iterations"] = (
                context.get("detector_feedback_iterations", 0) + 1
            )
            context["detector_attempt"] += 1
            context = self._run_step(
                workflow,
                "detector",
                context,
                attempt=context["detector_attempt"],
            )
            context = self._run_step(
                workflow,
                "detector_adversarial",
                context,
                attempt=context["detector_attempt"],
            )

        detector_adversarial: AdversarialReviewAlertOutput = context[
            "detector_adversarial"
        ]
        if (
            detector_adversarial.requires_classification_feedback
            and context.get("detector_feedback_iterations", 0) >= effective_max
        ):
            raise AdversarialFeedbackLimitExceededError(
                f"Adversarial review (detector) "
                f"{AdversarialFeedbackLimitExceededError.MESSAGE_MARKER} "
                f"{context.get('detector_feedback_iterations', 0)} feedback loop(s) "
                f"back to detector: {detector_adversarial.feedback}"
            )
        return context

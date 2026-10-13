from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
from functools import lru_cache
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any
from uuid import UUID

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.technical_metrics_dtos import (
    RecordWorkflowStepMetricsInput,
)
from src.application.use_cases.metrics.evaluate_alert_reasoning import (
    is_sampled_for_evaluation,
)
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
from src.application.dtos.discard_alert_dtos import DiscardAlertInput
from src.application.dtos.evaluate_deterministic_rules_dtos import (
    DeterministicRuleMatch,
)
from src.application.dtos.generate_agent_text_dtos import GenerateAgentTextInput
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
from src.application.dtos.research_dtos import ResearchRequest, ResearchSource
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.application.ports.alert_port import AlertOrigin, AlertStatus
from src.application.use_cases.alerts.raw_payload import RawAlertPayloadLoader
from src.application.ports.monitoring_port import (
    ATTR_ALERT_ID,
    ATTR_WORKFLOW_ATTEMPT,
    ATTR_WORKFLOW_EXECUTION_ID,
    ATTR_WORKFLOW_OUTCOME,
    ATTR_WORKFLOW_STEP,
    WORKFLOW_TOTAL_STEP,
    MonitoringSpan,
    span_dimension_attributes,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.configuration_port import (
    AdversarialConfig,
    AgentToolsConfig,
    ClassificationConfig,
    DocumentationStrategy,
    ExecutorConfig,
    ProfilingStrategyKey,
    SegmentSettings,
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
    get_discard_alert_use_case,
    get_enrich_profiling_fields_use_case,
    get_evaluate_deterministic_rules_use_case,
    get_generate_agent_text_use_case,
    get_model_repository,
    get_model_storage,
    get_post_process_alert_use_case,
    get_pre_process_alert_use_case,
    get_profile_alert_use_case,
    get_operational_settings_repository,
    get_record_alert_metrics_event_use_case,
    get_record_workflow_step_metrics_use_case,
    get_reasoning_evaluation_dispatcher,
    llm_step_models,
    get_route_alert_resolution_use_case,
    get_workflow_execution_repository,
    get_workflow_step_execution_repository,
    get_alert_object_storage,
    get_alert_schema_repository,
)
from src.domain.alerts.rule_conditions import evaluate_condition
from src.domain.alerts.transaction_history_selection import (
    parse_event_time,
    select_transaction_history,
)
from src.application.use_cases.alerts.agent_gate import agent_off_skip_reason
from src.application.use_cases.alerts.resolve_alert_segment import (
    ResolveAlertSegmentUseCase,
)
from src.domain.configurations.exceptions import ConfigurationNotFoundError
from src.domain.models.prompt_template import substitute_variables
from src.infrastructure.workflows.queued.queued_status_reporter import (
    QueuedWorkflowStatusReporter,
)
from src.infrastructure.workflows.celery.research_adapters import (
    HeuristicHistoryResearchPlanner,
    WorkflowVectorStoreRetriever,
)
from src.infrastructure.workflows.celery.history_pandas_research import HistoryPandasResearchAgent
from src.application.use_cases.research.delegated_research import (
    ResearchDelegationCoordinator,
    TimeBoundedResearchAgent,
    VectorStoreResearchAgent,
)

logger = logging.getLogger(__name__)

LINEAR_STEPS = (
    "pre_process",
    "deterministic",
    "profiling",
    "detector",
    "detector_adversarial",
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
        # Looked up at call time (not imported at module load) so tests can
        # swap factories.get_monitoring for an in-memory exporter.
        from src.infrastructure.workflows.celery.factories import get_monitoring

        self._monitoring = get_monitoring()
        self._workflow_span: MonitoringSpan | None = None
        # T2: the alert's known dimensions (aria.channel, aria.segment, ...)
        # from its metrics snapshot - refreshed after every metrics event and
        # copied onto each step span.
        self._dimensions: dict[str, str] = {}
        self._raw_payloads: RawAlertPayloadLoader | None = None

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

        started = time.perf_counter()
        alert = self._alerts.get(workflow.alert_id)
        self._dimensions = span_dimension_attributes(
            alert.metrics if alert is not None else None
        )
        span = self._monitoring.start(
            "alert_review_workflow",
            "workflow",
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
    ) -> dict[str, Any]:
        alert = self._alerts.get(workflow.alert_id)
        origin = AlertOrigin((workflow.input or {}).get("origin") or "manual")
        skip_reason = agent_off_skip_reason(
            origin, get_operational_settings_repository().get()
        )
        if skip_reason is not None:
            return self._skip(workflow, origin, skip_reason)

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
                    continue
                context = self._run_step(workflow, step_name, context)
                if step_name == "pre_process":
                    self._persist_schema_comparison(workflow, context)
                    context = _resolve_segment(context)
                    config = context.get("active_configuration")
                    if config is not None:
                        self._alerts.update(
                            workflow.alert_id,
                            configuration_id=config.configuration_id,
                            configuration_version=config.version,
                        )
                    self._record_metrics(
                        workflow,
                        AlertMetricsEventType.PRE_PROCESSED,
                        roles=context["pre_process"].roles,
                        segment=context.get("segment_code"),
                        configuration_id=(
                            config.configuration_id if config is not None else None
                        ),
                    )
                    self._persist_pre_process(workflow, context)
                if step_name == "profiling":
                    # Rubrics are part of profiling context, rather than a
                    # public workflow stage.  This preserves the workflow
                    # contract while making their evidence available to the
                    # Detector immediately afterwards.
                    context["rubrics"] = _run_rubrics(context)
                if step_name == "deterministic":
                    match: DeterministicRuleMatch = context["deterministic"]
                    if match.matched:
                        # Terminal for this run - skip profiling through
                        # post_process entirely. See DiscardAlertUseCase's
                        # own docstring for why this only logs today.
                        get_discard_alert_use_case().execute(
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
                if step_name == "detector":
                    detector_output: ClassifyAlertOutput = context["detector"]
                    if detector_output.is_fraud == "not_fraud":
                        # Not a discard (no DiscardAlertUseCase log) - this
                        # is a normal "no action needed" conclusion, same
                        # as an analyst deciding "pass" would be. Executor
                        # and post_process still run normally below,
                        # reading this synthetic AnalystReviewAlertOutput
                        # exactly like a real one.
                        context["analyst"] = AnalystReviewAlertOutput(
                            decision="pass",
                            reasoning=(
                                "Detector determined this alert is not "
                                f"fraud: {detector_output.reasoning}"
                            ),
                        )
                        skip_steps |= {
                            "detector_adversarial",
                            "classification",
                            "adversarial",
                            "analyst",
                        }
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

            if discarded:
                match = context["deterministic"]
                duration = (
                    datetime.now(timezone.utc) - workflow.created_at
                ).total_seconds()
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
            finished_at = datetime.now(timezone.utc)
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
            if not discarded:
                self._dispatch_reasoning_evaluation(workflow)
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
            self._record_metrics(
                workflow,
                AlertMetricsEventType.WORKFLOW_FINISHED,
                status=AlertStatus.FAILED,
            )
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
            # After the escalation, so the steps carry the alert's final
            # status for this attempt. Steps of an attempt that Celery will
            # retry are counted now (they ran); the next attempt's call
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
    ) -> dict[str, Any]:
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
        now = datetime.now(timezone.utc)
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
        return {"status": "skipped", "workflow_execution_id": str(workflow.id)}

    def _record_metrics(
        self,
        workflow: WorkflowExecutionRecord,
        event_type: AlertMetricsEventType,
        **fields: Any,
    ) -> None:
        # Best effort: a metrics failure must never fail (and so Celery-
        # retry) the alert review. Re-recording the same event on a retry is
        # a no-op (RecordAlertMetricsEvent compares snapshots), and the
        # daily reconciliation repairs anything lost here.
        try:
            snapshot = get_record_alert_metrics_event_use_case().execute(
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
                "Metrics event %s failed for alert %s", event_type.value, workflow.alert_id
            )

    def _record_step_metrics(self, workflow: WorkflowExecutionRecord) -> None:
        # R8 technical rollups from the run's persisted step records (call
        # after self._status.flush()). Best effort like _record_metrics:
        # exactly-once per step execution is RecordWorkflowStepMetrics'
        # job, so calling it again on a retry/escalation is harmless.
        try:
            config_overrides = (workflow.input or {}).get("config_overrides") or {}
            get_record_workflow_step_metrics_use_case().execute(
                RecordWorkflowStepMetricsInput(
                    alert_id=workflow.alert_id,
                    workflow_execution_id=workflow.id,
                    step_models=llm_step_models(
                        config_overrides.get("model_overrides") or {}
                    ),
                )
            )
        except Exception:
            logger.exception("Step metrics failed for alert %s", workflow.alert_id)

    def _dispatch_reasoning_evaluation(self, workflow: WorkflowExecutionRecord) -> None:
        # D6: a sampled share of finished alerts goes to the LLM-judge in
        # its own Celery task, off this run's critical path. Sampling is
        # deterministic per alert and the judge is idempotent, so a
        # duplicate dispatch can't double count.
        try:
            rate = get_operational_settings_repository().get().reasoning_evaluation_sample_rate
            if is_sampled_for_evaluation(workflow.alert_id, rate):
                get_reasoning_evaluation_dispatcher().dispatch(
                    workflow.alert_id, workflow.id
                )
        except Exception:
            logger.exception(
                "Reasoning evaluation dispatch failed for alert %s", workflow.alert_id
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

        step_started = time.perf_counter()
        step_span = self._monitoring.start(
            f"alert_review_workflow.{step_name}",
            "workflow.step",
            metadata={
                ATTR_ALERT_ID: str(workflow.alert_id),
                ATTR_WORKFLOW_STEP: step_name,
                ATTR_WORKFLOW_ATTEMPT: attempt,
                **self._dimensions,
            },
        )
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
            self._persist_agent_step(workflow, context, step_name, db_output)
            self._finish_step_span(
                step_span, step_name, WorkflowStepStatus.SUCCEEDED, step_started
            )
            return context
        except Exception as exc:
            self._finish_step_span(
                step_span, step_name, WorkflowStepStatus.FAILED, step_started, str(exc)
            )
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

    def _persist_pre_process(self, workflow, context: dict[str, Any]) -> None:
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

    def _persist_schema_comparison(self, workflow, context: dict[str, Any]) -> None:
        comparison = context.get("schema_comparison")
        if comparison is not None:
            self._workflows.update(workflow.id, schema_comparison=comparison)

    def _persist_agent_step(
        self, workflow, context: dict[str, Any], step_name: str, db_output: Any
    ) -> None:
        alert = self._alerts.get(workflow.alert_id)
        if alert is None or alert.raw_payload_ref is None:
            return
        schema = get_alert_schema_repository().get_active()
        if schema is None:
            return
        summary = dict(alert.agent_output)
        for field in schema.fields:
            if field.data_source.value != "aria" or not field.field_ds_loc:
                continue
            value = _relative_value(db_output, field.field_ds_loc)
            if value is not None:
                summary[field.field] = value
        current = context.setdefault("agent_outputs", {})
        current[step_name] = db_output
        ref = get_alert_object_storage().put_text(
            f"alerts/{workflow.alert_id}/agent-output.json",
            json.dumps(current, ensure_ascii=False, default=str),
            "application/json",
        )
        self._alerts.update(
            workflow.alert_id,
            agent_output=summary,
            agent_output_ref=ref,
        )

    def _load_raw_payload(self, alert) -> dict[str, Any]:
        if alert is None:
            return {}
        if alert.raw_payload_ref is None:
            # Hand-written workflow fixtures use canonical input directly;
            # persisted alerts always have raw_payload_ref.
            return alert.input
        if self._raw_payloads is None:
            self._raw_payloads = RawAlertPayloadLoader(get_alert_object_storage())
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

    def _run_detector_adversarial_review(
        self,
        workflow: WorkflowExecutionRecord,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Twin of _run_adversarial_review, for the Detector/Adversarial
        # (detector) pair instead of Clasificación/Adversarial
        # (clasificador) - kept as a separate method rather than a
        # generalized/parameterized one to avoid touching the existing,
        # already-covered classification<->adversarial loop while adding
        # this one. Deliberately does NOT persist its iteration count onto
        # WorkflowExecutionRecord.feedback_iterations - that field already
        # means "classification feedback loops" (see the other loop
        # above); this loop's count only needs to exist for the duration
        # of this run() call, to bound its own retries.
        context = self._run_step(workflow, "detector_adversarial", context)
        effective_max = _effective_max_detector_feedback_iterations(workflow, context)
        while _needs_detector_feedback(context, effective_max):
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
            context = self._run_step(workflow, "detector_adversarial", context)

        detector_adversarial: AdversarialReviewAlertOutput = context[
            "detector_adversarial"
        ]
        if (
            detector_adversarial.requires_classification_feedback
            and context.get("detector_feedback_iterations", 0) >= effective_max
        ):
            raise AdversarialFeedbackLimitExceededError(
                f"Adversarial review (detector) still flagged issues after "
                f"{context['detector_feedback_iterations']} feedback loop(s) "
                f"back to detector: {detector_adversarial.feedback}"
            )
        return context


class AdversarialFeedbackLimitExceededError(Exception):
    """Raised when an adversarial review step keeps rejecting its paired
    primary step (classification, or detector) past the workflow's/
    segment's allowed feedback loop-backs, so the alert must escalate to a
    human analyst instead of looping forever."""


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
    workflow_input = context.get("input") or {}
    payload = (
        workflow_input["alert_payload"]
        if "alert_payload" in workflow_input
        else context.get("raw_payload")
    ) or {}
    workflow_execution_id, step_id = _step_reporting_ids(context)
    use_case = get_pre_process_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
    )
    candidate_version = workflow_input.get("schema_version")
    candidate_schema = (
        get_alert_schema_repository().get(int(candidate_version))
        if candidate_version is not None
        else None
    )
    candidate = use_case.execute(
        PreProcessAlertInput(
            alert_id=UUID(context["alert_id"]),
            payload=payload,
            schema=candidate_schema,
        )
    )
    if workflow_input.get("origin") != AlertOrigin.TEST_RUN.value:
        return candidate
    # With no pin the candidate was already produced from the active schema;
    # avoid a second repository read and preserve the single pre-process pass.
    active_schema = (
        get_alert_schema_repository().get_active()
        if candidate_version is not None
        else None
    )
    if candidate_version is None or (
        active_schema is not None and active_schema.version == candidate.schema_version
    ):
        active = candidate
    else:
        active = get_pre_process_alert_use_case(
            status_reporter=None, workflow_execution_id=None, step_id=None
        ).execute(
            PreProcessAlertInput(
                alert_id=UUID(context["alert_id"]),
                payload=payload,
                schema=active_schema,
            )
        )
    context["schema_comparison"] = {
        "active": _pre_process_comparison_value(active),
        "candidate": _pre_process_comparison_value(candidate),
    }
    return candidate


def _pre_process_comparison_value(result: PreProcessAlertOutput) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "input": result.input,
        "labels": result.labels,
        "history_prev_alerta": result.history,
    }


def _run_deterministic(context: dict[str, Any]) -> DeterministicRuleMatch:
    segment = _active_segment(context)
    if segment is None:
        return DeterministicRuleMatch(matched=False)
    deterministic_cfg = segment.agent.deterministic
    pre_process: PreProcessAlertOutput = context["pre_process"]
    fields = pre_process.input
    return get_evaluate_deterministic_rules_use_case().execute(
        deterministic_cfg.rules, fields, alert_filter=deterministic_cfg.alert_filter
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


_PROFILING_STRATEGY_OPERATION_MAP = {
    ProfilingStrategyKey.USUARIO: "user_profile",
    ProfilingStrategyKey.TRANSACCION: "transaction_profile",
    ProfilingStrategyKey.TRANSACCIONAL: "transactional_profile",
}


def _segment_tool_kwargs(cfg: AgentToolsConfig) -> dict[str, Any]:
    # Same kwargs shape for every ReAct step with the shared "Herramientas
    # del agente" block (Detector, its Adversarial, Classification, its
    # Adversarial) - each passes its own config.
    # calculator needs no extra config beyond the switch; check_watchlist
    # additionally needs which watchlists to check and which alert field's
    # value to check against them - only registered when all three
    # (enabled, ids, compare field) are actually set. The vector-store
    # research is exposed as a tool (search_vector_store) the
    # agent calls itself, bounded by max_delegations interactions.
    enabled_tools: set[str] = set()
    if cfg.calculator_enabled:
        enabled_tools.add("calculator")
    kwargs: dict[str, Any] = {"enabled_tools": enabled_tools}
    if cfg.watchlist_enabled and cfg.watchlist_ids and cfg.watchlist_compare_field:
        enabled_tools.add("check_watchlist")
        kwargs["watchlist_ids"] = cfg.watchlist_ids
        kwargs["watchlist_compare_field"] = cfg.watchlist_compare_field
    vector_store = cfg.delegated_research.vector_store
    if vector_store.enabled and vector_store.vector_store_instance_id:
        from src.infrastructure.workflows.celery.factories import (
            get_monitoring,
            get_search_fraud_knowledge_use_case,
        )

        kwargs["vector_store_research"] = BoundedResearchTool(
            TimeBoundedResearchAgent(
                VectorStoreResearchAgent(
                    WorkflowVectorStoreRetriever(
                        get_search_fraud_knowledge_use_case(),
                        vector_store.vector_store_instance_id,
                    ),
                    vector_store,
                ),
                ResearchSource.VECTOR_STORE,
                vector_store.timeout_seconds,
                monitoring=get_monitoring(),
            ),
            ResearchSource.VECTOR_STORE,
            max_interactions=vector_store.max_delegations,
        )
    return kwargs


def _variables_pool(context: dict[str, Any], segment: SegmentSettings) -> dict[str, Any]:
    # {variable} substitution pool shared by every prompt in this segment's
    # pipeline (profiling's own main_prompt/categorization_prompt, plus
    # classification/adversarial/analyst's extra_instructions) - base alert
    # fields plus this segment's field-enrichment recipe outputs. There's
    # only one field_enrichment recipe set per segment (profiling's - see
    # ProfilingConfig), reused here rather than duplicated. Not
    # PreProcessAlertOutput.enrichment (an unrelated dict of raw fetched
    # context: aric_signals/customer_profile/transaction_history/
    # personal_data_changes, consumed as-is by profile/classify/adversarial).
    pre_process: PreProcessAlertOutput = context["pre_process"]
    current = pre_process.input
    history = [
        dataclasses.asdict(entry)
        for entry in pre_process.enrichment.get("transaction_history", [])
    ]
    enrichment_values = get_enrich_profiling_fields_use_case().execute(
        segment.agent.profiling.field_enrichment, current, history
    )
    return {**current, **enrichment_values}


def _run_profiling(context: dict[str, Any]) -> ProfileAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, "profiling")
    segment_kwargs: dict[str, Any] = {}
    if not overrides.get("system_prompt"):
        segment = _active_segment(context)
        if segment is not None:
            variables_pool = _variables_pool(context, segment)
            extra_instructions = {
                _PROFILING_STRATEGY_OPERATION_MAP[s.key]: substitute_variables(
                    s.main_prompt, variables_pool
                )
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
            input_fields=pre_process.input,
            segments=config.segments,
            roles=pre_process.roles,
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


def _effective_max_detector_feedback_iterations(
    workflow: WorkflowExecutionRecord, context: dict[str, Any]
) -> int:
    segment = _active_segment(context)
    if segment is not None:
        return segment.agent.detector_adversarial.max_cycles
    return workflow.max_feedback_iterations


def _run_detector(context: dict[str, Any]) -> ClassifyAlertOutput:
    # Reuses ClassifyAlertUseCase (same is_fraud/fraud_classification/
    # reasoning ReAct shape - see its step_name param) rather than a
    # separate DetectAlertUseCase class: Detector's job is the same binary
    # "is this fraud" call, just gating whether Clasificación's more
    # detailed taxonomy pass runs at all (see run()'s "detector" handling)
    # instead of being the final answer.
    #
    # With XGBoost enabled the model scores first: >= fraud threshold or
    # < uncertainty threshold is a direct decision (no LLM call); only the
    # band in between reaches the LLM, with the model output as evidence.
    segment = _active_segment(context)
    detector_cfg = segment.agent.detector if segment is not None else None
    model_score = _model_score_for(context, detector_cfg)
    if model_score is not None and model_score.is_fraud != "unknown":
        return ClassifyAlertOutput(
            is_fraud=model_score.is_fraud,
            fraud_classification="unknown",
            reasoning=model_score.reasoning,
            model_output=model_score.as_output(),
        )
    return _run_classify_step(context, "detector", detector_cfg, model_score)


def _run_classification(context: dict[str, Any]) -> ClassifyAlertOutput:
    segment = _active_segment(context)
    classification_cfg = segment.agent.classification if segment is not None else None
    return _run_classify_step(
        context,
        "classification",
        classification_cfg,
        _model_score_for(context, classification_cfg),
    )


def _run_classify_step(
    context: dict[str, Any],
    step_name: str,
    cfg: ClassificationConfig | None,
    model_score: _XGBoostScore | None,
) -> ClassifyAlertOutput:
    """Detector and Clasificación: same ReAct use case, same tool block.

    The history analysis runs only if the agent stays inconclusive, then
    the agent answers again with its findings (see _history_rounds).
    """
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, step_name)
    segment_kwargs: dict[str, Any] = {}
    if cfg is not None and not overrides.get("system_prompt"):
        segment = _active_segment(context)
        extra_instructions = ""
        if cfg.prompt:
            extra_instructions = substitute_variables(
                cfg.prompt, _variables_pool(context, segment)
            )
        if step_name == "detector":
            extra_instructions += _rubric_prompt_context(context)
        if model_score is not None:
            extra_instructions += model_score.prompt_block()
        if extra_instructions:
            segment_kwargs["extra_instructions"] = extra_instructions
        segment_kwargs.update(_segment_tool_kwargs(cfg))
        if cfg.output_labels:
            segment_kwargs["output_labels"] = cfg.output_labels
        if cfg.max_thought_iterations:
            segment_kwargs["max_iterations"] = cfg.max_thought_iterations
    evaluation_labels = _evaluation_labels(context)
    step_input = ClassifyAlertInput(
        alert_id=UUID(context["alert_id"]),
        pre_process=context["pre_process"],
        profile=context["profiling"],
        expected_classification=evaluation_labels.get("marcacion_final"),
        ground_truth_tipo=evaluation_labels.get("tipo"),
    )

    def run(kwargs: dict[str, Any]) -> ClassifyAlertOutput:
        return get_classify_alert_use_case(
            status_reporter=context.get("status_reporter"),
            workflow_execution_id=workflow_execution_id,
            step_id=step_id,
            step_name=step_name,
            **overrides,
            **kwargs,
        ).execute(step_input)

    output = run(segment_kwargs)
    if cfg is not None:
        output = _history_rounds(
            context, cfg, segment_kwargs, output, run,
            is_open=lambda out: out.is_fraud == "unknown",
            reasoning_of=lambda out: out.reasoning,
        )
    if model_score is not None:
        output = dataclasses.replace(output, model_output=model_score.as_output())
    return output


def _run_detector_adversarial(context: dict[str, Any]) -> AdversarialReviewAlertOutput:
    segment = _active_segment(context)
    return _run_adversarial_step(
        context,
        "detector_adversarial",
        segment.agent.detector_adversarial if segment is not None else None,
        # Reuses AdversarialReviewAlertInput's `classification` field for
        # the detector's output - same ClassifyAlertOutput shape.
        reviewed=context["detector"],
    )


def _run_adversarial(context: dict[str, Any]) -> AdversarialReviewAlertOutput:
    segment = _active_segment(context)
    return _run_adversarial_step(
        context,
        "adversarial",
        segment.agent.adversarial if segment is not None else None,
        reviewed=context["classification"],
    )


def _run_adversarial_step(
    context: dict[str, Any],
    step_name: str,
    cfg: AdversarialConfig | None,
    reviewed: ClassifyAlertOutput,
) -> AdversarialReviewAlertOutput:
    """Both adversarials: same use case, same tool block. The history
    analysis runs only when the review challenges the result, then the
    review runs again with its findings (see _history_rounds)."""
    workflow_execution_id, step_id = _step_reporting_ids(context)
    overrides = _step_overrides(context, step_name)
    segment_kwargs: dict[str, Any] = {}
    model_score = _model_score_for(context, cfg)
    if cfg is not None and not overrides.get("system_prompt"):
        segment = _active_segment(context)
        extra_instructions = ""
        if cfg.prompt:
            extra_instructions = substitute_variables(
                cfg.prompt, _variables_pool(context, segment)
            )
        if model_score is not None:
            extra_instructions += model_score.prompt_block()
        if extra_instructions:
            segment_kwargs["extra_instructions"] = extra_instructions
        segment_kwargs.update(_segment_tool_kwargs(cfg))
        max_iterations = getattr(cfg, "max_thought_iterations", None)
        if max_iterations:
            segment_kwargs["max_iterations"] = max_iterations
    step_input = AdversarialReviewAlertInput(
        alert_id=UUID(context["alert_id"]),
        pre_process=context["pre_process"],
        profile=context["profiling"],
        classification=reviewed,
    )

    def run(kwargs: dict[str, Any]) -> AdversarialReviewAlertOutput:
        return get_adversarial_review_alert_use_case(
            status_reporter=context.get("status_reporter"),
            workflow_execution_id=workflow_execution_id,
            step_id=step_id,
            step_name=step_name,
            **overrides,
            **kwargs,
        ).execute(step_input)

    output = run(segment_kwargs)
    if cfg is not None:
        output = _history_rounds(
            context, cfg, segment_kwargs, output, run,
            is_open=lambda out: out.requires_classification_feedback,
            reasoning_of=lambda out: out.feedback or out.reasoning,
        )
    if model_score is not None:
        output = dataclasses.replace(output, model_output=model_score.as_output())
    return output


def _run_rubrics(context: dict[str, Any]) -> dict[str, Any]:
    """Score every segment rubric against enriched alert fields.

    Additive scorecard: each matched condition adds its points to its
    rubric's score. Condition points of a rubric sum to 100 (enforced on
    save, see CreateConfigurationRequest), so each score is 0-100.
    """
    segment = _active_segment(context)
    if segment is None:
        return {"scores": [], "evaluated": 0}
    fields = _variables_pool(context, segment)
    scores: list[dict[str, Any]] = []
    for rubric in segment.agent.rubrics:
        matched = [
            condition for condition in rubric.conditions
            if evaluate_condition(condition, fields)
        ]
        scores.append({
            "id": rubric.id,
            "name": rubric.name,
            "score": sum(condition.score for condition in matched),
            "max_score": sum(condition.score for condition in rubric.conditions),
            "matched_condition_ids": [condition.id for condition in matched],
        })
    return {"scores": scores, "evaluated": len(scores)}


def _rubric_prompt_context(context: dict[str, Any]) -> str:
    rubric_result = context.get("rubrics")
    if not rubric_result or not rubric_result.get("scores"):
        return ""
    lines = "\n".join(
        f"- {item['name']}: {item['score']:g}/{item['max_score']:g}"
        for item in rubric_result["scores"]
    )
    return (
        "\n\nPuntajes de rúbricas configuradas (evidencia adicional; "
        f"evalúalos junto con las demás señales):\n{lines}"
    )


def _history_research(
    context: dict[str, Any], cfg: AgentToolsConfig, reasoning: str
) -> list[dict[str, Any]]:
    """Run the history analysis over the configured history slice."""
    settings = cfg.delegated_research.history_pandas
    pre_process: PreProcessAlertOutput = context["pre_process"]
    history = pre_process.enrichment.get("transaction_history") or []
    if not settings.enabled or settings.max_delegations <= 0 or not history:
        return []
    # Selector: time window before the alert + most recent N rows. Column
    # restriction (allowed_columns) is enforced by the agent itself.
    selected = select_transaction_history(
        history,
        columns=[],
        window_days=settings.window_days,
        max_transactions=settings.max_history_rows,
        reference_time=parse_event_time(pre_process.roles.get("event_time")),
    )
    agent = TimeBoundedResearchAgent(
        HistoryPandasResearchAgent(
            HeuristicHistoryResearchPlanner(pre_process.roles.get("amount")),
            settings,
            history_provider=lambda _request: selected,
        ),
        ResearchSource.HISTORY_PANDAS,
        settings.timeout_seconds,
        monitoring=_factories_monitoring(),
    )
    request = ResearchRequest(
        ResearchSource.HISTORY_PANDAS,
        "Investiga evidencia adicional en el historial de la alerta. "
        f"Razonamiento previo: {reasoning}",
    )
    results = ResearchDelegationCoordinator({ResearchSource.HISTORY_PANDAS: agent}).delegate(
        [request], is_inconclusive=lambda: True, accept=lambda _result: None
    )
    return [dataclasses.asdict(result) for result in results]


def _factories_monitoring():
    # Call-time lookup so tests can swap factories.get_monitoring.
    from src.infrastructure.workflows.celery.factories import get_monitoring

    return get_monitoring()


_MAX_HISTORY_ROUNDS = 5


def _history_rounds(
    context: dict[str, Any],
    cfg: AgentToolsConfig,
    segment_kwargs: dict[str, Any],
    output: Any,
    run: Callable[[dict[str, Any]], Any],
    *,
    is_open: Callable[[Any], bool],
    reasoning_of: Callable[[Any], str],
) -> Any:
    """Up to history_pandas.max_delegations rounds (capped at 5) while the
    step stays open (inconclusive / challenged): each round runs the
    history analysis, then the step once more with every finding so far.

    Stops early when the step concludes, or when a round brings back the
    same findings as the previous one - re-asking would only repeat the
    same prompt.
    """
    rounds = min(
        cfg.delegated_research.history_pandas.max_delegations, _MAX_HISTORY_ROUNDS
    )
    research: list[dict[str, Any]] = []
    previous: list[Any] | None = None
    for _ in range(rounds):
        if not is_open(output):
            break
        found = _history_research(context, cfg, reasoning_of(output))
        evidence = [(item.get("status"), item.get("findings")) for item in found]
        if not found or evidence == previous:
            break
        previous = evidence
        research.extend(found)
        output = dataclasses.replace(
            run(_with_research(segment_kwargs, research)),
            research_delegations=list(research),
        )
    return output


def _with_research(kwargs: dict[str, Any], research: list[dict[str, Any]]) -> dict[str, Any]:
    final_kwargs = dict(kwargs)
    final_kwargs["extra_instructions"] = (
        str(final_kwargs.get("extra_instructions") or "")
        + "\n\nInvestigación delegada: análisis de historial. Úsala como "
        "evidencia adicional y responde ahora con tu conclusión final:\n"
        f"{research}"
    )
    return final_kwargs


@dataclasses.dataclass(frozen=True)
class _XGBoostScore:
    score: float
    model_id: str
    model_tag: str
    is_fraud: str  # "fraud" | "not_fraud" | "unknown" (uncertainty band)
    verdict: str
    fraud_threshold: float
    uncertainty_threshold: float
    top_features: list[dict[str, Any]] | None

    @property
    def reasoning(self) -> str:
        return f"XGBoost ({self.model_tag}) obtuvo {self.score:.4f} y {self.verdict}."

    def as_output(self) -> dict[str, Any]:
        # Kept apart from the LLM's reasoning on every step output: the
        # model's own result plus which variables weighed most (SHAP).
        return {
            "model_id": self.model_id,
            "model_tag": self.model_tag,
            "score": self.score,
            "prediction": self.is_fraud,
            "verdict": self.verdict,
            "fraud_threshold": self.fraud_threshold,
            "uncertainty_threshold": self.uncertainty_threshold,
            "top_features": self.top_features,
        }

    def prompt_block(self) -> str:
        return (
            "\n\nSalida del modelo XGBoost (evidencia separada del resto de "
            "señales; top_features son las variables con más peso en la "
            "predicción según SHAP):\n"
            + json.dumps(self.as_output(), ensure_ascii=False, default=str)
        )


@lru_cache(maxsize=4)
def _load_model_bundle(storage_ref: str) -> dict[str, Any]:
    # A trained bundle is immutable per storage_ref - cache the unpickled
    # model instead of re-downloading it for every alert.
    from io import BytesIO

    import joblib

    return joblib.load(BytesIO(get_model_storage().get_bytes(storage_ref)))


def _model_score_for(
    context: dict[str, Any], cfg: AgentToolsConfig | None
) -> _XGBoostScore | None:
    if cfg is None or not cfg.use_xgboost_model:
        return None
    return _score_with_xgboost(context, cfg)


def _score_with_xgboost(
    context: dict[str, Any], cfg: AgentToolsConfig
) -> _XGBoostScore | None:
    """Score the alert with the configured trained bundle.

    Returns None (the step runs LLM-only) when no trained model is
    available - a model-registry problem shouldn't fail alert review.
    Raw model results are cached per alert and model, so steps sharing a
    model score once; thresholds/SHAP are applied per step's config.
    """
    model_id = cfg.xgboost_model_id
    repository = get_model_repository()
    model = repository.get(UUID(model_id)) if model_id else repository.get_active()
    if model is None or model.storage_ref is None:
        logger.warning(
            "XGBoost enabled but model %s is not trained or does not exist; "
            "alert %s continues LLM-only.",
            model_id or "<active>", context.get("alert_id"),
        )
        return None
    cache: dict[str, dict[str, Any]] = context.setdefault("_xgboost_results", {})
    result = cache.get(str(model.id))
    if result is None:
        from src.infrastructure.entrypoint.mcp.scoring import score_row

        result = score_row(_load_model_bundle(model.storage_ref), _alert_payload(context))
        cache[str(model.id)] = result
    score = float(result["score"])
    if score >= cfg.xgboost_fraud_threshold:
        is_fraud, verdict = "fraud", "superó el umbral de fraude"
    elif score < cfg.xgboost_uncertainty_threshold:
        is_fraud, verdict = "not_fraud", "quedó por debajo del umbral de incertidumbre"
    else:
        is_fraud, verdict = "unknown", "quedó en la banda de incertidumbre"
    return _XGBoostScore(
        score=score,
        model_id=str(model.id),
        model_tag=model.tag,
        is_fraud=is_fraud,
        verdict=verdict,
        fraud_threshold=cfg.xgboost_fraud_threshold,
        uncertainty_threshold=cfg.xgboost_uncertainty_threshold,
        top_features=result.get("top_features") if cfg.xgboost_shap_enabled else None,
    )


def _alert_payload(context: dict[str, Any]) -> dict[str, Any]:
    # The raw payload may contain test-run labels. Detector model features
    # follow the same canonical input contract as every other agent step.
    pre_process: PreProcessAlertOutput | None = context.get("pre_process")
    return pre_process.input if pre_process is not None else {}


def _evaluation_labels(context: dict[str, Any]) -> dict[str, Any]:
    pre_process: PreProcessAlertOutput | None = context.get("pre_process")
    if pre_process is None:
        return {}
    # PreProcessAlertUseCase built this mapping by walking the active schema's
    # is_label fields. It is already the canonical, schema-shaped evaluation
    # view; never recover labels from the raw workflow payload here.
    return dict(pre_process.labels)


def _run_analyst(context: dict[str, Any]) -> AnalystReviewAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    segment_kwargs: dict[str, Any] = {}
    segment = _active_segment(context)
    if segment is not None:
        segment_kwargs["handling_prompt"] = segment.agent.analyst.prompt
        # Reuses Classification's vector-store research selection (see
        # ResolveAnalystPlaybookUseCase's docstring) - Analyst has no
        # vector store picker of its own.
        classification_vector_store = (
            segment.agent.classification.delegated_research.vector_store
        )
        segment_kwargs["vector_store_instance_id"] = (
            classification_vector_store.vector_store_instance_id
            if classification_vector_store.enabled
            else None
        )
    use_case = get_analyst_review_alert_use_case(
        status_reporter=context.get("status_reporter"),
        workflow_execution_id=workflow_execution_id,
        step_id=step_id,
        **_step_overrides(context, "analyst"),
        **segment_kwargs,
    )
    return use_case.execute(
        AnalystReviewAlertInput(
            alert_id=UUID(context["alert_id"]),
            pre_process=context["pre_process"],
            profile=context["profiling"],
            classification=context["classification"],
        )
    )


_ARIC_MARKING_SYSTEM_PROMPT = (
    "Eres un agente que redacta el comentario de marcación ARIC para una "
    "alerta de fraude, a partir de la instrucción y los datos entregados. "
    "Escribe un comentario breve, claro y accionable para quien revise la "
    "marcación después."
)

_DOCUMENTADOR_SYSTEM_PROMPT = (
    "Eres un agente que redacta la documentación final de una alerta de "
    "fraude para el historial del caso, a partir de la instrucción y los "
    "datos entregados. Sé claro, objetivo y conciso."
)


def _executor_variables_pool(
    context: dict[str, Any], segment: SegmentSettings
) -> dict[str, Any]:
    # Same pool as classification/adversarial (_variables_pool), extended
    # with the decision data the executor step's own prompts (ARIC
    # marking, voicebot script, documentador, escalation) are actually
    # about - neither exists yet when profiling/classification build
    # their own pool, so this stays a superset built fresh here.
    pool = dict(_variables_pool(context, segment))
    classification: ClassifyAlertOutput | None = context.get("classification")
    analyst: AnalystReviewAlertOutput | None = context.get("analyst")
    if classification is not None:
        pool.setdefault("fraud_classification", classification.fraud_classification)
        pool.setdefault("is_fraud", classification.is_fraud)
        pool.setdefault("classification_reasoning", classification.reasoning)
    if analyst is not None:
        pool.setdefault("analyst_decision", analyst.decision)
        pool.setdefault("analyst_reasoning", analyst.reasoning)
    return pool


def _generate_agent_text(
    prompt: str, pool: dict[str, Any], system_prompt: str, operation_name: str
) -> str:
    if not prompt:
        return ""
    use_case = get_generate_agent_text_use_case(
        system_prompt=system_prompt, operation_name=operation_name
    )
    output = use_case.execute(
        GenerateAgentTextInput(prompt=substitute_variables(prompt, pool))
    )
    return output.text


def _voicebot_script(
    executor_cfg: ExecutorConfig, context: dict[str, Any], pool: dict[str, Any]
) -> str:
    # Plain template concatenation (base + matching category prompt), no
    # LLM call - unlike aric_marking/documentador's "agent" strategy, the
    # UI describes this field as prompts that "se concatenan
    # dinámicamente", not text for an agent to draft.
    voicebot_cfg = executor_cfg.voicebot_call
    parts = [
        substitute_variables(voicebot_cfg.base_prompt, pool)
    ] if voicebot_cfg.base_prompt else []
    classification: ClassifyAlertOutput | None = context.get("classification")
    fraud_classification = (
        classification.fraud_classification if classification is not None else None
    )
    # taxonomy_id is matched directly against the classification's
    # fraud_classification label - both are meant to name the same
    # taxonomy entry (see Taxonomy/VoicebotCategoryPrompt in
    # configuration_port.py). If that ever needs to become an explicit
    # id lookup instead of a string match, this is the one place to change.
    for category_prompt in voicebot_cfg.category_prompts:
        if (
            category_prompt.prompt
            and fraud_classification is not None
            and category_prompt.taxonomy_id == fraud_classification
        ):
            parts.append(substitute_variables(category_prompt.prompt, pool))
    return "\n\n".join(parts)


def _run_executor(context: dict[str, Any]) -> dict[str, Any]:
    analyst: AnalystReviewAlertOutput = context["analyst"]
    alert_id = UUID(context["alert_id"])
    segment = _active_segment(context)
    executor_cfg = segment.agent.executor if segment is not None else None

    # The analyst saw availability when deciding, but it may be gone now:
    # reserve the voicebot slot / confirm an analyst is available, and
    # follow the playbook's fallbacks otherwise.
    routing = get_route_alert_resolution_use_case().execute(
        alert_id=str(alert_id),
        decision=analyst.decision,
        playbook=analyst.playbook,
    )
    decision = routing.decision
    routing_detail: dict[str, Any] = {}
    if routing.fallbacks:
        routing_detail["decided_action"] = analyst.decision
        routing_detail["fallbacks"] = [
            dataclasses.asdict(step) for step in routing.fallbacks
        ]
    if routing.block_mode is not None:
        routing_detail["block_mode"] = routing.block_mode
    if routing.reservation_id is not None:
        routing_detail["voicebot_reservation_id"] = routing.reservation_id

    if decision == "pass":
        return {
            "executed_action": "none",
            "detail": "Analyst decision was pass - no action required.",
            **routing_detail,
        }

    if decision == "scale_to_analyst":
        alert = get_alert_repository().get(alert_id)
        event_id = alert.event_id if alert is not None else str(alert_id)
        reason = analyst.reasoning
        if executor_cfg is not None and executor_cfg.analyst_escalation.prompt:
            pool = _executor_variables_pool(context, segment)
            reason = substitute_variables(
                executor_cfg.analyst_escalation.prompt, pool
            )
        ref = get_analyst_escalation_dispatcher().dispatch(
            alert_id=alert_id,
            workflow_execution_id=UUID(context["workflow_execution_id"]),
            event_id=event_id,
            session_id=None,
            reason=reason,
        )
        return {
            "executed_action": decision,
            "dispatch_backend": ref.backend,
            "dispatch_external_id": ref.external_id,
            **routing_detail,
        }

    if decision in ("block", "bidi", "voicebot"):
        content: str | None = None
        if executor_cfg is not None:
            pool = _executor_variables_pool(context, segment)
            if decision == "voicebot":
                content = _voicebot_script(executor_cfg, context, pool) or None
            else:
                content = (
                    _generate_agent_text(
                        executor_cfg.aric_marking.prompt,
                        pool,
                        _ARIC_MARKING_SYSTEM_PROMPT,
                        "aric_marking",
                    )
                    or None
                )
        ref = get_alert_action_dispatcher().dispatch(decision, alert_id, content=content)
        return {
            "executed_action": decision,
            "dispatch_backend": ref.backend,
            "dispatch_external_id": ref.external_id,
            **routing_detail,
        }

    raise ValueError(f"Unsupported analyst decision: {decision}")


def _run_post_process(context: dict[str, Any]) -> PostProcessAlertOutput:
    analyst: AnalystReviewAlertOutput = context["analyst"]
    documentation = ""
    segment = _active_segment(context)
    if segment is not None:
        documentador = segment.agent.executor.documentador
        pool = _executor_variables_pool(context, segment)
        if documentador.strategy == DocumentationStrategy.TEMPLATE:
            if documentador.template:
                documentation = substitute_variables(documentador.template, pool)
        elif documentador.strategy == DocumentationStrategy.AGENT:
            documentation = _generate_agent_text(
                documentador.agent_prompt,
                pool,
                _DOCUMENTADOR_SYSTEM_PROMPT,
                "documentador",
            )
    use_case = get_post_process_alert_use_case()
    return use_case.execute(
        PostProcessAlertInput(
            alert_id=UUID(context["alert_id"]),
            workflow_started_at=datetime.fromisoformat(
                context["workflow_started_at"]
            ),
            resolution_path=analyst.decision,
            documentation=documentation,
        )
    )


def _execute_placeholder_step(
    step_name: str,
    context: dict[str, Any],
) -> Any:
    if step_name == "pre_process":
        return _run_pre_process(context)
    if step_name == "deterministic":
        return _run_deterministic(context)
    if step_name == "profiling":
        return _run_profiling(context)
    if step_name == "detector":
        return _run_detector(context)
    if step_name == "detector_adversarial":
        return _run_detector_adversarial(context)
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


def _relative_value(output: Any, location: str) -> Any:
    value = output
    for part in location.split("."):
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
    return value


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


def _needs_detector_feedback(
    context: dict[str, Any],
    max_feedback_iterations: int,
) -> bool:
    detector_adversarial: AdversarialReviewAlertOutput | None = context.get(
        "detector_adversarial"
    )
    return bool(
        detector_adversarial is not None
        and detector_adversarial.requires_classification_feedback
        and context.get("detector_feedback_iterations", 0) < max_feedback_iterations
    )


def _step_input(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": context["alert_id"],
        "classification_attempt": context.get("classification_attempt", 1),
    }

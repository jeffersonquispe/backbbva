"""Resolution-side workflow steps: analyst, executor and post_process."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any
from uuid import UUID

from src.application.dtos.analyst_review_alert_dtos import (
    AnalystReviewAlertInput,
    AnalystReviewAlertOutput,
)
from src.application.dtos.generate_agent_text_dtos import GenerateAgentTextInput
from src.application.dtos.post_process_alert_dtos import (
    PostProcessAlertInput,
    PostProcessAlertOutput,
)
from src.application.ports.configuration_port import DocumentationStrategy
from src.application.use_cases.alerts.alert_review_policy import active_segment
from src.domain.models.prompt_template import substitute_variables
from src.infrastructure.workflows.celery.executor_text import (
    _ARIC_MARKING_SYSTEM_PROMPT,
    _DOCUMENTADOR_SYSTEM_PROMPT,
    _executor_variables_pool,
    _voicebot_script,
)
from src.infrastructure.workflows.celery.factories import (
    get_alert_action_dispatcher,
    get_alert_repository,
    get_analyst_escalation_dispatcher,
    get_analyst_review_alert_use_case,
    get_generate_agent_text_use_case,
    get_post_process_alert_use_case,
    get_route_alert_resolution_use_case,
)
from src.infrastructure.workflows.celery.step_context import (
    _step_overrides,
    _step_reporting_ids,
)


def _run_analyst(context: dict[str, Any]) -> AnalystReviewAlertOutput:
    workflow_execution_id, step_id = _step_reporting_ids(context)
    segment_kwargs: dict[str, Any] = {}
    segment = active_segment(context)
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


def _run_executor(context: dict[str, Any]) -> dict[str, Any]:
    analyst: AnalystReviewAlertOutput = context["analyst"]
    alert_id = UUID(context["alert_id"])
    segment = active_segment(context)
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
            reason = substitute_variables(executor_cfg.analyst_escalation.prompt, pool)
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
        ref = get_alert_action_dispatcher().dispatch(
            decision, alert_id, content=content
        )
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
    segment = active_segment(context)
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
            workflow_started_at=datetime.fromisoformat(context["workflow_started_at"]),
            resolution_path=analyst.decision,
            documentation=documentation,
        )
    )

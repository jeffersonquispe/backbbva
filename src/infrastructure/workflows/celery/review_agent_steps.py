"""LLM/ML reasoning workflow steps: detector, classification and their
adversarial reviews, plus the optional XGBoost pre-scoring."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any
from uuid import UUID

from src.application.dtos.adversarial_review_alert_dtos import (
    AdversarialReviewAlertInput,
    AdversarialReviewAlertOutput,
)
from src.application.dtos.classify_alert_dtos import (
    ClassifyAlertInput,
    ClassifyAlertOutput,
)
from src.application.use_cases.alerts.alert_review_policy import active_segment
from src.domain.configurations.entities import (
    AdversarialConfig,
    AgentToolsConfig,
    ClassificationConfig,
)
from src.domain.models.prompt_template import substitute_variables
from src.infrastructure.workflows.celery.factories import (
    get_adversarial_review_alert_use_case,
    get_classify_alert_use_case,
)
from src.infrastructure.workflows.celery.history_research import _history_rounds
from src.infrastructure.workflows.celery.step_context import (
    _evaluation_labels,
    _rubric_prompt_context,
    _step_overrides,
    _step_reporting_ids,
    _variables_pool,
)
from src.infrastructure.workflows.celery.xgboost_score import _XGBoostScore

logger = logging.getLogger(__name__)


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
        from src.infrastructure.workflows.celery.task_factories import (
            get_vector_store_research_tool,
        )

        kwargs["vector_store_research"] = get_vector_store_research_tool(vector_store)
    return kwargs


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
    segment = active_segment(context)
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
    segment = active_segment(context)
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
        segment = active_segment(context)
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
            context,
            cfg,
            segment_kwargs,
            output,
            run,
            is_open=lambda out: out.is_fraud == "unknown",
            reasoning_of=lambda out: out.reasoning,
        )
    if model_score is not None:
        output = dataclasses.replace(output, model_output=model_score.as_output())
    return output


def _run_detector_adversarial(context: dict[str, Any]) -> AdversarialReviewAlertOutput:
    segment = active_segment(context)
    return _run_adversarial_step(
        context,
        "detector_adversarial",
        segment.agent.detector_adversarial if segment is not None else None,
        # Reuses AdversarialReviewAlertInput's `classification` field for
        # the detector's output - same ClassifyAlertOutput shape.
        reviewed=context["detector"],
    )


def _run_adversarial(context: dict[str, Any]) -> AdversarialReviewAlertOutput:
    segment = active_segment(context)
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
        segment = active_segment(context)
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
            context,
            cfg,
            segment_kwargs,
            output,
            run,
            is_open=lambda out: out.requires_classification_feedback,
            reasoning_of=lambda out: out.feedback or out.reasoning,
        )
    if model_score is not None:
        output = dataclasses.replace(output, model_output=model_score.as_output())
    return output


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
    cache: dict[str, dict[str, Any]] = context.setdefault("_xgboost_results", {})
    model_id = cfg.xgboost_model_id
    shadow_observer = None
    routed_model_id = None
    try:
        from src.infrastructure.workflows.celery.task_factories import (
            get_agent_shadow_observer,
        )

        shadow_observer = get_agent_shadow_observer()
        routed_model_id = shadow_observer.route_model_id(str(context["alert_id"]))
        if routed_model_id is not None:
            model_id = routed_model_id
    except Exception as exc:  # noqa: BLE001 - release routing fails closed
        logger.warning("Agent rollout lookup failed; use active model: %s", exc)
        model_id = cfg.xgboost_model_id
    cache_key = model_id or "active"
    result = cache.get(cache_key)
    if result is None:
        from src.infrastructure.workflows.celery.task_factories import (
            get_model_scoring_port,
        )

        try:
            result = get_model_scoring_port().score_alert(
                str(context["alert_id"]), model_id
            )
        except Exception as exc:  # noqa: BLE001 - scoring outage falls back to LLM
            logger.warning("MCP scoring failed; alert continues LLM-only: %s", exc)
            return None
        if "error" in result:
            logger.warning(
                "MCP has no trained model for alert %s; continuing LLM-only: %s",
                context.get("alert_id"),
                result["error"],
            )
            return None
        cache[cache_key] = result
    if shadow_observer is not None:
        active_result = result
        candidate_prediction = None
        if routed_model_id is not None and str(result.get("model_id")) == routed_model_id:
            try:
                from src.infrastructure.workflows.celery.task_factories import (
                    get_model_scoring_port,
                )

                scoring_port = get_model_scoring_port()
                active_key = cfg.xgboost_model_id or "active"
                active_result = cache.get(active_key)
                if active_result is None:
                    active_result = scoring_port.score_alert(
                        str(context["alert_id"]), cfg.xgboost_model_id
                    )
                    if "error" not in active_result:
                        cache[active_key] = active_result
                candidate_prediction = bool(result.get("predicted_positive"))
            except Exception as exc:  # noqa: BLE001 - shadow never blocks production
                logger.warning("Baseline comparison scoring failed safely: %s", exc)
                active_result = {"error": "BASELINE_SCORING_FAILED"}
        if "error" in active_result:
            logger.warning(
                "Canary baseline unavailable; alert continues without XGBoost: %s",
                active_result["error"],
            )
            return None
        try:
            shadow_observer.execute(
                str(context["alert_id"]),
                bool(active_result.get("predicted_positive")),
                candidate_prediction,
            )
        except Exception as exc:  # noqa: BLE001 - shadow never blocks production
            logger.warning("Agent shadow scoring failed safely: %s", exc)
    model_id = str(result["model_id"])
    score = float(result["score"])
    if score >= cfg.xgboost_fraud_threshold:
        is_fraud, verdict = "fraud", "superó el umbral de fraude"
    elif score < cfg.xgboost_uncertainty_threshold:
        is_fraud, verdict = "not_fraud", "quedó por debajo del umbral de incertidumbre"
    else:
        is_fraud, verdict = "unknown", "quedó en la banda de incertidumbre"
    return _XGBoostScore(
        score=score,
        model_id=model_id,
        model_tag=str(result.get("model_tag", "unknown")),
        is_fraud=is_fraud,
        verdict=verdict,
        fraud_threshold=cfg.xgboost_fraud_threshold,
        uncertainty_threshold=cfg.xgboost_uncertainty_threshold,
        top_features=result.get("top_features") if cfg.xgboost_shap_enabled else None,
    )

from __future__ import annotations

from typing import Any

from src.application.dtos.analyst_review_alert_dtos import AnalystReviewAlertOutput
from src.application.dtos.classify_alert_dtos import ClassifyAlertOutput
from src.domain.configurations.entities import (
    ExecutorConfig,
    SegmentSettings,
)
from src.domain.models.prompt_template import substitute_variables
from src.infrastructure.workflows.celery.step_context import _variables_pool

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


def _voicebot_script(
    executor_cfg: ExecutorConfig, context: dict[str, Any], pool: dict[str, Any]
) -> str:
    # Plain template concatenation (base + matching category prompt), no
    # LLM call - unlike aric_marking/documentador's "agent" strategy, the
    # UI describes this field as prompts that "se concatenan
    # dinámicamente", not text for an agent to draft.
    voicebot_cfg = executor_cfg.voicebot_call
    parts = (
        [substitute_variables(voicebot_cfg.base_prompt, pool)]
        if voicebot_cfg.base_prompt
        else []
    )
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

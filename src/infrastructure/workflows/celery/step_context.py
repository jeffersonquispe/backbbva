from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.domain.configurations.entities import (
    SegmentSettings,
)
from src.infrastructure.workflows.celery.factories import (
    get_enrich_profiling_fields_use_case,
)


def _step_reporting_ids(context: dict[str, Any]) -> tuple[UUID | None, UUID | None]:
    status_reporter = context.get("status_reporter")
    if status_reporter is None:
        return None, None
    step_id = context.get("current_step_id")
    return (
        UUID(context["workflow_execution_id"]),
        UUID(step_id) if step_id else None,
    )


def _pre_process_comparison_value(result: PreProcessAlertOutput) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "input": result.input,
        "labels": result.labels,
        "history_prev_alerta": result.history,
    }


def _step_overrides(context: dict[str, Any], step_name: str) -> dict[str, str | None]:
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


def _variables_pool(
    context: dict[str, Any], segment: SegmentSettings
) -> dict[str, Any]:
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

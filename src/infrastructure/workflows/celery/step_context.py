from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput
from src.domain.configurations.entities import (
    SegmentSettings,
)
from src.infrastructure.llm.catalog.element_llm import get_resolve_element_llm
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
    # Which deployment the step runs with: the test's override, else the
    # selection of the configuration this run resolved at its start (pinned
    # for tests), else None = the step's own default. The effective choice is
    # kept in the context so the workflow can record it with the step output.
    configuration = context.get("active_configuration")
    selection = getattr(getattr(configuration, "general", None), "llm_selection", None)
    resolved = get_resolve_element_llm().execute(
        step_name,
        override=(config_overrides.get("model_overrides") or {}).get(step_name),
        selection=selection,
    )
    context.setdefault("llm_resolutions", {})[step_name] = resolved.as_dict()
    return {
        "system_prompt": (config_overrides.get("prompt_overrides") or {}).get(
            step_name
        ),
        "model": resolved.deployment if resolved.source != "default" else None,
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


def _optimizer_vector_store_pin(pin: Any) -> tuple[str, int]:
    """(instance id, generation) of an optimizer evaluation's vector-store
    pin - its version is the generation number (see the component
    resolver)."""
    if not isinstance(pin, dict) or not isinstance(pin.get("entity_id"), str):
        raise ValueError("OPTIMIZER_VECTOR_STORE_PIN_REQUIRED")
    try:
        return pin["entity_id"], int(pin["version"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("OPTIMIZER_VECTOR_STORE_PIN_REQUIRED") from error

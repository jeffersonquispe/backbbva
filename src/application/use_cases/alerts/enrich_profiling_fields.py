from __future__ import annotations

from typing import Any

from src.domain.models.feature_recipe import evaluate_feature_definition, validate_feature_definition


class EnrichProfilingFieldsUseCase:
    """Evaluates a segment's field-enrichment recipes against a single alert,
    in-process - no ports, no queueing. Unlike models' PreviewFeaturesUseCase
    (evaluates up to 100 dataset rows behind a Celery task, because it's
    triggered from a browser request), this runs on exactly one row inside
    an already-async workflow step, so a plain synchronous call is enough."""

    def execute(
        self, configuration: dict[str, Any], current: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        # No recipes configured yet is the default/untouched state for a
        # segment (see configuration_port.py's _default_field_enrichment) -
        # validate_feature_definition itself requires 1-200 recipes, so an
        # empty list must short-circuit here rather than fail validation.
        if not configuration.get("recipes"):
            return {}
        definition = validate_feature_definition(configuration)
        history_key = definition.get("mappings", {}).get("history") or "history"
        row = {**current, history_key: history}
        return evaluate_feature_definition(definition, row, validated=True)["values"]

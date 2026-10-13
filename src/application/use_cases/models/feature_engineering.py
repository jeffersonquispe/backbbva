from __future__ import annotations

import json
from copy import deepcopy

from src.application.errors import ValidationError
from src.application.ports.clock_port import Clock
from src.application.ports.feature_template_port import (
    FeatureTemplate,
    FeatureTemplateRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.models.feature_recipe import (
    describe_capabilities,
    evaluate_feature_definition,
    validate_feature_definition,
)


class FeatureRecipeProblem(ValidationError):
    """A validation problem that can point the editor to one recipe."""

    def __init__(self, message: str, recipe: dict):
        super().__init__(message)
        self.detail = {
            "code": "invalid_feature_recipe",
            "recipe_id": recipe.get("id"),
            "recipe_name": recipe.get("name"),
            "field": "missing.value"
            if "Missing constant must match" in message
            else None,
            "message": message,
        }


class FeatureCapabilitiesUseCase:
    """Publishes the recipe engine's operation/output_type catalog so the
    mapping/transformations editor can build its pickers from this - the
    live validation contract - instead of hand-copying it client-side."""

    def execute(self) -> dict:
        return describe_capabilities()


class PreviewFeaturesUseCase:
    def validate(
        self, configuration: dict, rows: list[dict], target_field: str | None = None
    ) -> dict:
        """Validate a preview before it is put on the worker queue."""
        forbidden_paths = (target_field,) if target_field else ()
        try:
            definition = validate_feature_definition(
                configuration, forbidden_paths=forbidden_paths
            )
        except ValueError as exc:
            # The complete definition may fail for a single mapping. Re-run
            # each mapping independently to return a stable ID to the editor;
            # global errors (duplicates, malformed mappings, etc.) remain
            # ordinary validation errors because there is no safe target.
            if isinstance(configuration, dict) and isinstance(
                configuration.get("recipes"), list
            ):
                for recipe in configuration["recipes"]:
                    if not isinstance(recipe, dict):
                        continue
                    candidate = deepcopy(configuration)
                    candidate["recipes"] = [recipe]
                    try:
                        validate_feature_definition(
                            candidate, forbidden_paths=forbidden_paths
                        )
                    except ValueError as recipe_exc:
                        if str(recipe_exc) == str(exc):
                            raise FeatureRecipeProblem(str(exc), recipe) from exc
            raise ValidationError(str(exc)) from exc
        if not 1 <= len(rows) <= 100:
            raise ValidationError("La vista previa requiere entre 1 y 100 filas")
        if len(json.dumps(rows, ensure_ascii=False)) > 2_000_000:
            raise ValidationError("La muestra supera el límite de 2 MB")
        return definition

    def execute(
        self, configuration: dict, rows: list[dict], target_field: str | None = None
    ) -> dict:
        definition = self.validate(configuration, rows, target_field)
        return {
            "rows": [
                evaluate_feature_definition(definition, row, validated=True)
                for row in rows
            ]
        }


class FeatureTemplatesUseCase:
    def __init__(
        self,
        repository: FeatureTemplateRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ):
        self._repository = repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def list(self) -> list[FeatureTemplate]:
        return self._repository.list()

    def create(
        self, name: str, description: str, configuration: dict
    ) -> FeatureTemplate:
        if not name.strip() or len(name) > 120 or len(description) > 2000:
            raise ValidationError(
                "Indica un nombre de hasta 120 caracteres y una descripción de hasta 2000"
            )
        try:
            definition = validate_feature_definition(configuration)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if len(json.dumps(definition, ensure_ascii=False)) > 200_000:
            raise ValidationError("La configuración supera el límite de 200 KB")
        return self._repository.create(
            FeatureTemplate(
                id=str(self._id_generator.new_id()),
                name=name.strip(),
                description=description,
                configuration=deepcopy(definition),
                created_at=self._clock.now(),
            )
        )

    def delete(self, template_id: str) -> None:
        self._repository.delete(template_id)

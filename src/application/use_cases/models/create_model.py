from __future__ import annotations

from copy import deepcopy

from src.application.dtos.model_dtos import CreateModelInput, ModelOutput
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.model_port import (
    ModelRecord,
    ModelRepository,
    ModelStatus,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


def _to_output(model: ModelRecord) -> ModelOutput:
    return ModelOutput(
        id=model.id,
        tag=model.tag,
        description=model.description,
        status=model.status,
        dataset_name=model.dataset_name,
        target_field=model.target_field,
        positive_labels=model.positive_labels,
        feature_transforms=model.feature_transforms,
        active=model.active,
        metrics=model.metrics,
        storage_ref=model.storage_ref,
        created_at=model.created_at,
        updated_at=model.updated_at,
        created_by=model.created_by,
        error=model.error,
        historical_features=model.historical_features,
        training_config=model.training_config,
        training_report=model.training_report,
        feature_configuration=deepcopy(model.feature_configuration),
    )


class CreateModelUseCase:
    def __init__(
        self,
        repository: ModelRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, input: CreateModelInput) -> ModelOutput:
        if input.feature_configuration is not None:
            from src.domain.models.feature_recipe import validate_feature_definition

            validate_feature_definition(
                input.feature_configuration, forbidden_paths=(input.target_field,)
            )
        now = self._clock.now()
        model = ModelRecord(
            id=self._id_generator.new_id(),
            tag=input.tag,
            description=input.description,
            status=ModelStatus.DRAFT,
            dataset_name=input.dataset_name,
            target_field=input.target_field,
            positive_labels=input.positive_labels,
            feature_transforms=input.feature_transforms,
            active=False,
            metrics=None,
            storage_ref=None,
            created_at=now,
            updated_at=now,
            created_by=input.created_by,
            historical_features=input.historical_features,
            training_config=input.training_config,
            feature_configuration=deepcopy(input.feature_configuration),
        )
        saved = self._repository.create(model)
        return _to_output(saved)

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.dtos.model_dtos import CreateModelInput, ModelOutput
from src.application.ports.model_port import (
    ModelRecord,
    ModelRepository,
    ModelStatus,
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
    )


class CreateModelUseCase:
    def __init__(self, repository: ModelRepository) -> None:
        self._repository = repository

    def execute(self, input: CreateModelInput) -> ModelOutput:
        now = datetime.now(timezone.utc)
        model = ModelRecord(
            id=uuid.uuid4(),
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
        )
        saved = self._repository.create(model)
        return _to_output(saved)

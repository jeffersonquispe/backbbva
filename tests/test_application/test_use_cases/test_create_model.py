from __future__ import annotations

from uuid import UUID

from src.application.dtos.model_dtos import CreateModelInput
from src.application.ports.model_port import (
    FieldTransform,
    FieldTransformKind,
    ModelRecord,
    ModelStatus,
)
from src.application.use_cases.models.create_model import CreateModelUseCase


class InMemoryModelRepository:
    def __init__(self) -> None:
        self.models: dict[UUID, ModelRecord] = {}

    def create(self, model: ModelRecord) -> ModelRecord:
        self.models[model.id] = model
        return model

    def get(self, model_id: UUID) -> ModelRecord | None:
        return self.models.get(model_id)

    def list(self) -> list[ModelRecord]:
        return list(self.models.values())

    def get_active(self) -> ModelRecord | None:
        return next((m for m in self.models.values() if m.active), None)

    def update(self, model: ModelRecord) -> ModelRecord:
        self.models[model.id] = model
        return model

    def activate(self, model_id: UUID) -> ModelRecord:
        for model in self.models.values():
            model.active = model.id == model_id
        return self.models[model_id]

    def delete(self, model_id: UUID) -> None:
        self.models.pop(model_id, None)


def test_create_model_starts_as_draft_with_uuid4_id() -> None:
    repository = InMemoryModelRepository()
    use_case = CreateModelUseCase(repository)

    output = use_case.execute(
        CreateModelInput(
            tag="xus-v1",
            description="Primer modelo XUS",
            dataset_name="dataset-1",
            target_field="marcacion_final",
            positive_labels=["risk", "risk-suspected"],
            feature_transforms=[
                FieldTransform(field="channel", kind=FieldTransformKind.CATEGORICAL),
                FieldTransform(field="amount_value", kind=FieldTransformKind.NUMERIC),
            ],
            created_by="tester",
        )
    )

    assert isinstance(output.id, UUID)
    assert output.status == ModelStatus.DRAFT
    assert output.active is False
    assert output.tag == "xus-v1"
    assert repository.get(output.id) is not None

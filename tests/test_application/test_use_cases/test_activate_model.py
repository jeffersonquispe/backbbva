from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.model_port import ModelRecord, ModelStatus
from src.application.use_cases.models.activate_model import ActivateModelUseCase


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


def _ready_model(tag: str) -> ModelRecord:
    now = datetime.now(UTC)
    return ModelRecord(
        id=UUID(int=hash(tag) % (2**128)),
        tag=tag,
        description="",
        status=ModelStatus.READY,
        dataset_name="dataset-1",
        target_field="marcacion_final",
        created_at=now,
        updated_at=now,
    )


def test_activate_model_flips_previous_active_off() -> None:
    repository = InMemoryModelRepository()
    v1 = _ready_model("v1")
    v2 = _ready_model("v2")
    repository.create(v1)
    repository.create(v2)
    repository.activate(v1.id)
    use_case = ActivateModelUseCase(repository)

    output = use_case.execute(v2.id)

    assert output.active is True
    assert repository.get(v1.id).active is False
    assert repository.get_active().id == v2.id

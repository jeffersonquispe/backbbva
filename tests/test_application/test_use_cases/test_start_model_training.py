from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.ports.model_port import ModelRecord, ModelStatus
from src.application.use_cases.models.start_model_training import StartModelTrainingUseCase
from src.domain.models.exceptions import ModelNotFoundError


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


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {}

    def create(self, operation: AsyncOperationRecord) -> AsyncOperationRecord:
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        return self.operations.get(operation_id)

    def list(self, status=None, limit: int = 100) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        return [
            op
            for op in self.operations.values()
            if op.status
            in (AsyncOperationStatus.PENDING, AsyncOperationStatus.RUNNING)
        ][:limit]

    def update(self, operation_id: UUID, **changes: Any) -> AsyncOperationRecord | None:
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        operation.status = changes.get("status") or operation.status
        operation.result = changes.get("result", operation.result)
        operation.error = changes.get("error", operation.error)
        return operation

    def delete(self, operation_id: UUID) -> None:
        self.operations.pop(operation_id, None)


class RecordingModelTrainingDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[tuple[UUID, UUID]] = []

    def dispatch(self, model_id: UUID, async_operation_id: UUID) -> None:
        self.dispatched.append((model_id, async_operation_id))


def _draft_model() -> ModelRecord:
    now = datetime.now(timezone.utc)
    return ModelRecord(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        tag="xus-v1",
        description="test model",
        status=ModelStatus.DRAFT,
        dataset_name="dataset-1",
        target_field="marcacion_final",
        positive_labels=["risk"],
        created_at=now,
        updated_at=now,
    )


def test_start_model_training_dispatches_and_marks_training() -> None:
    models = InMemoryModelRepository()
    model = _draft_model()
    models.create(model)
    async_operations = InMemoryAsyncOperationRepository()
    dispatcher = RecordingModelTrainingDispatcher()
    use_case = StartModelTrainingUseCase(models, async_operations, dispatcher)

    output = use_case.execute(model.id)

    assert models.get(model.id).status == ModelStatus.TRAINING
    assert dispatcher.dispatched == [(model.id, output.async_operation_id)]
    operation = async_operations.get(output.async_operation_id)
    assert operation is not None
    assert operation.operation_type == "model_training"
    assert operation.payload["model_id"] == str(model.id)


def test_start_model_training_raises_when_model_missing() -> None:
    use_case = StartModelTrainingUseCase(
        InMemoryModelRepository(),
        InMemoryAsyncOperationRepository(),
        RecordingModelTrainingDispatcher(),
    )
    with pytest.raises(ModelNotFoundError):
        use_case.execute(UUID("22222222-2222-2222-2222-222222222222"))


def test_start_model_training_raises_when_already_trained_or_training() -> None:
    models = InMemoryModelRepository()
    model = _draft_model()
    model.status = ModelStatus.TRAINING
    models.create(model)
    use_case = StartModelTrainingUseCase(
        models, InMemoryAsyncOperationRepository(), RecordingModelTrainingDispatcher()
    )
    with pytest.raises(ValueError, match="solo puede entrenarse una vez"):
        use_case.execute(model.id)


def test_failed_dispatch_cannot_be_retried():
    models = InMemoryModelRepository()
    model = _draft_model()
    models.create(model)
    operations = InMemoryAsyncOperationRepository()
    dispatcher = RecordingModelTrainingDispatcher()
    def fail(*args):
        raise RuntimeError("queue unavailable")
    dispatcher.dispatch = fail
    use_case = StartModelTrainingUseCase(models, operations, dispatcher)
    with pytest.raises(RuntimeError):
        use_case.execute(model.id)
    assert model.status == ModelStatus.FAILED
    assert next(iter(operations.operations.values())).status == AsyncOperationStatus.FAILED
    dispatcher.dispatch = lambda *args: None
    with pytest.raises(ValueError, match="solo puede entrenarse una vez"):
        use_case.execute(model.id)


def test_active_model_cannot_be_retrained():
    models = InMemoryModelRepository()
    model = _draft_model()
    model.active = True
    models.create(model)
    with pytest.raises(ValueError, match="solo puede entrenarse una vez"):
        StartModelTrainingUseCase(models, InMemoryAsyncOperationRepository(), RecordingModelTrainingDispatcher()).execute(model.id)

from __future__ import annotations

from uuid import UUID

from src.application.ports.model_training_dispatcher_port import (
    ModelTrainingDispatcher,
)
from src.infrastructure.entrypoint.worker.celery.tasks import train_model_task


class CeleryModelTrainingDispatcher(ModelTrainingDispatcher):
    def dispatch(self, model_id: UUID, async_operation_id: UUID) -> None:
        train_model_task.delay(str(model_id), str(async_operation_id))

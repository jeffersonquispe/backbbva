from __future__ import annotations

from uuid import UUID

from src.application.ports.model_training_dispatcher_port import (
    ModelTrainingDispatcher,
)
from src.infrastructure.queues.celery.app import app

_TASK_NAME = "models.train"


class CeleryModelTrainingDispatcher(ModelTrainingDispatcher):
    def dispatch(self, model_id: UUID, async_operation_id: UUID) -> None:
        app.send_task(_TASK_NAME, args=[str(model_id), str(async_operation_id)])

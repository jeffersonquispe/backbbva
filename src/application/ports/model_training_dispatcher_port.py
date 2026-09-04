from __future__ import annotations

from uuid import UUID


class ModelTrainingDispatcher:
    """Kicks off async training of a model - see
    infrastructure/queues/celery/model_training_dispatcher.py for the Celery
    adapter and infrastructure/workflows/celery/model_training.py's
    train_model_task for what actually runs."""

    def dispatch(self, model_id: UUID, async_operation_id: UUID) -> None:
        raise NotImplementedError

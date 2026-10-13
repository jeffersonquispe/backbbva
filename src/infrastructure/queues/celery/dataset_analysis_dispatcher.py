from __future__ import annotations

from uuid import UUID

from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.infrastructure.queues.celery.app import app as celery_app


class CeleryDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def dispatch(self, dataset_name: str, operation_id: UUID | None = None) -> None:
        celery_app.send_task(
            "datasets.analyze",
            args=[dataset_name, str(operation_id) if operation_id else None],
        )

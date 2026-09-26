from __future__ import annotations

from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.infrastructure.entrypoint.worker.celery.tasks import analyze_dataset_task
from uuid import UUID


class CeleryDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def dispatch(self, dataset_name: str, operation_id: UUID | None = None) -> None:
        analyze_dataset_task.delay(dataset_name, str(operation_id) if operation_id else None)

from __future__ import annotations

from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.infrastructure.entrypoint.worker.celery.tasks import analyze_dataset_task


class CeleryDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def dispatch(self, dataset_name: str) -> None:
        analyze_dataset_task.delay(dataset_name)

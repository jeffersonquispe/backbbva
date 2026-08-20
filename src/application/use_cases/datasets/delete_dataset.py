from __future__ import annotations

from src.application.ports.dataset_analysis_port import (
    DatasetSampleRepository,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository


class DeleteDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        sample_repository: DatasetSampleRepository,
        summary_repository: DatasetSummaryRepository,
    ) -> None:
        self._datasets = dataset_repository
        self._samples = sample_repository
        self._summaries = summary_repository

    def execute(self, dataset_name: str) -> None:
        self._datasets.delete(dataset_name)
        self._samples.delete_by_dataset(dataset_name)
        self._summaries.delete(dataset_name)

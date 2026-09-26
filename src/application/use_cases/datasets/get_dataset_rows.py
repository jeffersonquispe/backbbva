from __future__ import annotations

from src.application.dtos.dataset_dtos import GetDatasetRowsInput, GetDatasetRowsOutput
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_analysis_port import DatasetSummaryRepository


class GetDatasetRowsUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository | None = None,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository

    def execute(self, input: GetDatasetRowsInput) -> GetDatasetRowsOutput:
        page, total = self._datasets.get_rows_page(
            input.name, input.offset, input.limit
        )
        summary = self._summaries.get(input.name) if self._summaries else None
        return GetDatasetRowsOutput(
            rows=page,
            total=summary.total_rows if summary is not None else total,
        )

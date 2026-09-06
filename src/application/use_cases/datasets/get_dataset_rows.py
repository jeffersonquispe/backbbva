from __future__ import annotations

from src.application.dtos.dataset_dtos import GetDatasetRowsInput, GetDatasetRowsOutput
from src.application.ports.dataset_port import DatasetRepository


class GetDatasetRowsUseCase:
    def __init__(self, dataset_repository: DatasetRepository) -> None:
        self._datasets = dataset_repository

    def execute(self, input: GetDatasetRowsInput) -> GetDatasetRowsOutput:
        page, total = self._datasets.get_rows_page(
            input.name, input.offset, input.limit
        )
        return GetDatasetRowsOutput(rows=page, total=total)

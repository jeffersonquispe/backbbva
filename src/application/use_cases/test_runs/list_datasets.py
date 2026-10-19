from __future__ import annotations

from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.domain.datasets.entities import DatasetRecord


class ListDatasetsUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository | None = None,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository

    def execute(self) -> list[DatasetRecord]:
        records = self._datasets.list()
        if self._summaries is None:
            return records
        return [
            DatasetRecord(
                name=record.name,
                row_count=(
                    summary.total_rows
                    if (summary := self._summaries.get(record.name))
                    else record.row_count
                ),
            )
            for record in records
        ]

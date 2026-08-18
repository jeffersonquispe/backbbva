from __future__ import annotations

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository


class ListDatasetsUseCase:
    def __init__(self, dataset_repository: DatasetRepository) -> None:
        self._datasets = dataset_repository

    def execute(self) -> list[DatasetRecord]:
        return self._datasets.list()

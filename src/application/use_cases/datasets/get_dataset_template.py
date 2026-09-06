from __future__ import annotations

import csv
import io

from src.application.dtos.dataset_dtos import GetDatasetTemplateOutput
from src.application.ports.dataset_port import DatasetRepository


class GetDatasetTemplateUseCase:
    def __init__(self, dataset_repository: DatasetRepository) -> None:
        self._datasets = dataset_repository

    def execute(self, name: str) -> GetDatasetTemplateOutput:
        fields = self._datasets.get_fields(name)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(fields)
        return GetDatasetTemplateOutput(
            filename=f"{name}_template.csv",
            content=buffer.getvalue(),
        )

from __future__ import annotations

import csv
import io

from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.get_dataset_template import (
    GetDatasetTemplateUseCase,
)


class InMemoryDatasetRepository(DatasetRepository):
    def __init__(self, fields: list[str]) -> None:
        self._fields = fields

    def list(self):
        return []

    def get_rows(self, name):
        return []

    def get_fields(self, name):
        return self._fields

    def get_rows_page(self, name, offset, limit):
        return [], 0

    def create(self, name, fields):
        pass

    def append_rows(self, name, rows):
        return 0

    def delete(self, name):
        pass


def test_get_dataset_template_returns_csv_quoted_header_and_filename() -> None:
    fields = ["eventId", "amount, currency", 'notes "quoted"']
    datasets = InMemoryDatasetRepository(fields)
    use_case = GetDatasetTemplateUseCase(datasets)

    output = use_case.execute("my_dataset")

    assert output.filename == "my_dataset_template.csv"
    parsed_rows = list(csv.reader(io.StringIO(output.content)))
    assert parsed_rows == [fields]

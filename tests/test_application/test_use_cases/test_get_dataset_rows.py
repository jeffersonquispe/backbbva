from __future__ import annotations

from typing import Any

from src.application.dtos.dataset_dtos import GetDatasetRowsInput
from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.get_dataset_rows import GetDatasetRowsUseCase


class FakeDatasetRepository(DatasetRepository):
    def __init__(self, page: list[dict[str, Any]], total: int) -> None:
        self.page = page
        self.total = total
        self.get_rows_page_calls: list[tuple[str, int, int]] = []

    def list(self):
        return []

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return []

    def get_fields(self, name: str) -> list[str]:
        return []

    def get_rows_page(self, name: str, offset: int, limit: int):
        self.get_rows_page_calls.append((name, offset, limit))
        return self.page, self.total

    def create(self, name: str, fields: list[str]) -> None:
        pass

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        return 0

    def delete(self, name: str) -> None:
        pass


def test_get_dataset_rows_passes_through_offset_and_limit() -> None:
    rows = [{"a": "1"}, {"a": "2"}]
    datasets = FakeDatasetRepository(page=rows, total=25)
    use_case = GetDatasetRowsUseCase(dataset_repository=datasets)

    output = use_case.execute(GetDatasetRowsInput(name="ds1", offset=10, limit=2))

    assert output.rows == rows
    assert output.total == 25
    assert datasets.get_rows_page_calls == [("ds1", 10, 2)]


def test_get_dataset_rows_uses_default_offset_and_limit() -> None:
    datasets = FakeDatasetRepository(page=[], total=0)
    use_case = GetDatasetRowsUseCase(dataset_repository=datasets)

    output = use_case.execute(GetDatasetRowsInput(name="empty_ds"))

    assert output.rows == []
    assert output.total == 0
    assert datasets.get_rows_page_calls == [("empty_ds", 0, 50)]

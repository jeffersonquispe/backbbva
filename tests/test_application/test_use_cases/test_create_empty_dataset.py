from __future__ import annotations

import pytest

from src.application.dtos.dataset_dtos import CreateEmptyDatasetInput
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.use_cases.datasets.create_empty_dataset import (
    CreateEmptyDatasetUseCase,
)


class InMemoryDatasetRepository(DatasetRepository):
    def __init__(self, existing_names: set[str] | None = None) -> None:
        self._existing_names = existing_names or set()
        self.created: list[tuple[str, list[str]]] = []

    def list(self):
        return []

    def get_rows(self, name):
        return []

    def get_fields(self, name):
        return []

    def get_rows_page(self, name, offset, limit):
        return [], 0

    def create(self, name: str, fields: list[str]) -> None:
        if name in self._existing_names:
            raise FileExistsError(name)
        self.created.append((name, fields))

    def append_rows(self, name, rows):
        return 0

    def delete(self, name):
        pass


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, DatasetSummaryRecord] = {}
        self.upserted: list[DatasetSummaryRecord] = []

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._by_name[summary.dataset_name] = summary
        self.upserted.append(summary)
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._by_name.get(dataset_name)

    def delete(self, dataset_name: str) -> None:
        self._by_name.pop(dataset_name, None)


def test_create_empty_dataset_creates_dataset_and_seeds_ready_summary() -> None:
    datasets = InMemoryDatasetRepository()
    summaries = InMemoryDatasetSummaryRepository()
    use_case = CreateEmptyDatasetUseCase(datasets, summaries)

    output = use_case.execute(
        CreateEmptyDatasetInput(name="new_dataset", fields=["eventId", "amount"])
    )

    assert output.name == "new_dataset"
    assert output.status == DatasetAnalysisStatus.READY
    assert datasets.created == [("new_dataset", ["eventId", "amount"])]

    summary = summaries.get("new_dataset")
    assert summary is not None
    assert summary.origin == DatasetOrigin.EMPTY
    assert summary.status == DatasetAnalysisStatus.READY
    assert summary.total_rows == 0
    assert summary.available_fields == ["eventId", "amount"]


def test_create_empty_dataset_propagates_file_exists_error_when_name_taken() -> None:
    datasets = InMemoryDatasetRepository(existing_names={"taken"})
    summaries = InMemoryDatasetSummaryRepository()
    use_case = CreateEmptyDatasetUseCase(datasets, summaries)

    with pytest.raises(FileExistsError):
        use_case.execute(CreateEmptyDatasetInput(name="taken", fields=["eventId"]))

    assert summaries.upserted == []

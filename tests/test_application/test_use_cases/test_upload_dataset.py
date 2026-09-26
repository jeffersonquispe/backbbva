from __future__ import annotations

import io
from typing import Any

import pytest

from src.application.dtos.dataset_dtos import UploadDatasetInput
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase


class RecordingDatasetRepository(DatasetRepository):
    def __init__(self, existing_names: set[str] | None = None) -> None:
        self._existing_names = existing_names or set()
        self.created_from_csv: list[tuple[str, bytes]] = []
        self.created_from_csv_files: list[tuple[str, bytes]] = []

    def list(self):
        return []

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return []

    def get_fields(self, name: str) -> list[str]:
        return []

    def get_rows_page(self, name: str, offset: int, limit: int):
        return [], 0

    def create(self, name: str, fields: list[str]) -> None:
        pass

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        if name in self._existing_names:
            raise FileExistsError(name)
        self.created_from_csv.append((name, content))

    def create_from_csv_file(self, name: str, file) -> None:
        if name in self._existing_names:
            raise FileExistsError(name)
        self.created_from_csv_files.append((name, file.read()))

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        return 0

    def delete(self, name: str) -> None:
        pass


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, DatasetSummaryRecord] = {}

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._by_name[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._by_name.get(dataset_name)

    def delete(self, dataset_name: str) -> None:
        self._by_name.pop(dataset_name, None)


class RecordingDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, dataset_name: str) -> None:
        self.dispatched.append(dataset_name)


def test_upload_dataset_stores_csv_seeds_summary_and_dispatches_analysis() -> None:
    datasets = RecordingDatasetRepository()
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = UploadDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        UploadDatasetInput(name="new_dataset", content=b"eventId\ne-1\n")
    )

    assert output.name == "new_dataset"
    assert output.status == DatasetAnalysisStatus.PENDING
    # Writing via DatasetRepository (not ObjectStoragePort directly) is the
    # point of this test: it guarantees the upload lands wherever
    # list()/get_rows() will actually look for it, regardless of which
    # storage backend DATASET_STORAGE_BACKEND selects.
    assert datasets.created_from_csv == [("new_dataset", b"eventId\ne-1\n")]
    summary = summaries.get("new_dataset")
    assert summary is not None
    assert summary.status == DatasetAnalysisStatus.PENDING
    assert summary.total_rows == 0
    assert dispatcher.dispatched == ["new_dataset"]


def test_upload_dataset_propagates_file_exists_error_when_name_taken() -> None:
    datasets = RecordingDatasetRepository(existing_names={"taken"})
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = UploadDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(FileExistsError):
        use_case.execute(UploadDatasetInput(name="taken", content=b"eventId\n"))

    assert summaries.get("taken") is None
    assert dispatcher.dispatched == []


def test_upload_dataset_streams_spooled_file_to_dataset_repository() -> None:
    datasets = RecordingDatasetRepository()
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = UploadDatasetUseCase(datasets, summaries, dispatcher)

    use_case.execute(
        UploadDatasetInput(
            name="streamed_dataset",
            file=io.BytesIO(b"eventId\\ne-1\\n"),
        )
    )

    assert datasets.created_from_csv == []
    assert datasets.created_from_csv_files == [
        ("streamed_dataset", b"eventId\\ne-1\\n")
    ]

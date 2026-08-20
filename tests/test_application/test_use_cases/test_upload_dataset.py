from __future__ import annotations

from src.application.dtos.dataset_dtos import UploadDatasetInput
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.object_storage_port import ObjectStoragePort, ObjectStorageRef
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase


class RecordingObjectStoragePort(ObjectStoragePort):
    def __init__(self) -> None:
        self.puts: list[tuple[str, bytes, str]] = []

    def put_bytes(self, key, content, content_type="application/octet-stream"):
        self.puts.append((key, content, content_type))
        return ObjectStorageRef(bucket="datasets", key=key, uri=f"s3://datasets/{key}")


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, DatasetSummaryRecord] = {}

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._by_name[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._by_name.get(dataset_name)


class RecordingDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, dataset_name: str) -> None:
        self.dispatched.append(dataset_name)


def test_upload_dataset_stores_csv_seeds_summary_and_dispatches_analysis() -> None:
    object_storage = RecordingObjectStoragePort()
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = UploadDatasetUseCase(
        object_storage=object_storage,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        UploadDatasetInput(name="new_dataset", content=b"eventId\ne-1\n")
    )

    assert output.name == "new_dataset"
    assert output.status == DatasetAnalysisStatus.PENDING
    assert object_storage.puts == [
        ("new_dataset.csv", b"eventId\ne-1\n", "text/csv")
    ]
    summary = summaries.get("new_dataset")
    assert summary is not None
    assert summary.status == DatasetAnalysisStatus.PENDING
    assert summary.total_rows == 0
    assert dispatcher.dispatched == ["new_dataset"]

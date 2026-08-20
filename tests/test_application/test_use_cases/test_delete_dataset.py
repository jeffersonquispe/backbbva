from __future__ import annotations

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSampleRecord,
    DatasetSampleRepository,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase


class InMemoryDatasetRepository(DatasetRepository):
    def __init__(self, names: set[str]) -> None:
        self._names = names
        self.deleted: list[str] = []

    def list(self) -> list[DatasetRecord]:
        return [DatasetRecord(name=n, row_count=0) for n in self._names]

    def get_rows(self, name: str) -> list[dict]:
        return []

    def delete(self, name: str) -> None:
        self._names.discard(name)
        self.deleted.append(name)


class InMemoryDatasetSampleRepository(DatasetSampleRepository):
    def __init__(self, by_dataset: dict[str, list[DatasetSampleRecord]]) -> None:
        self.by_dataset = by_dataset

    def create_batch(self, samples: list[DatasetSampleRecord]) -> None:
        for sample in samples:
            self.by_dataset.setdefault(sample.dataset_name, []).append(sample)

    def list_by_dataset(self, dataset_name: str) -> list[DatasetSampleRecord]:
        return self.by_dataset.get(dataset_name, [])

    def delete_by_dataset(self, dataset_name: str) -> None:
        self.by_dataset.pop(dataset_name, None)


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self, records: dict[str, DatasetSummaryRecord]) -> None:
        self._records = records

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._records[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._records.get(dataset_name)

    def delete(self, dataset_name: str) -> None:
        self._records.pop(dataset_name, None)


def test_delete_dataset_removes_csv_samples_and_summary() -> None:
    datasets = InMemoryDatasetRepository({"ds", "other"})
    samples = InMemoryDatasetSampleRepository(
        {
            "ds": [
                DatasetSampleRecord(
                    dataset_name="ds",
                    sample_id="00000000",
                    razon_marcacion="r",
                    marcacion_final="no-risk",
                    integration_point="ip",
                    tipo="NoFraude",
                    triggered_rules=None,
                )
            ]
        }
    )
    summaries = InMemoryDatasetSummaryRepository(
        {
            "ds": DatasetSummaryRecord(
                dataset_name="ds",
                status=DatasetAnalysisStatus.READY,
                total_rows=1,
                field_distributions={},
            )
        }
    )
    use_case = DeleteDatasetUseCase(datasets, samples, summaries)

    use_case.execute("ds")

    assert datasets.deleted == ["ds"]
    assert [d.name for d in datasets.list()] == ["other"]
    assert samples.list_by_dataset("ds") == []
    assert summaries.get("ds") is None


def test_delete_dataset_is_idempotent_when_dataset_already_gone() -> None:
    use_case = DeleteDatasetUseCase(
        InMemoryDatasetRepository(set()),
        InMemoryDatasetSampleRepository({}),
        InMemoryDatasetSummaryRepository({}),
    )

    use_case.execute("missing")  # must not raise

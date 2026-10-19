from __future__ import annotations

from typing import Protocol

from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSampleRecord,
    DatasetSummaryRecord,
)

__all__ = [
    "DatasetAnalysisStatus",
    "DatasetOrigin",
    "DatasetSampleRecord",
    "DatasetSampleRepository",
    "DatasetSummaryRecord",
    "DatasetSummaryRepository",
]


class DatasetSampleRepository(Protocol):
    def create_batch(self, samples: list[DatasetSampleRecord]) -> None: ...

    def list_by_dataset(self, dataset_name: str) -> list[DatasetSampleRecord]: ...

    def delete_by_dataset(self, dataset_name: str) -> None: ...


class DatasetSummaryRepository(Protocol):
    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord: ...

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None: ...

    def delete(self, dataset_name: str) -> None: ...

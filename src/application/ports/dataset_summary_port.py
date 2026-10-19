from __future__ import annotations

from typing import Protocol

from src.domain.datasets.entities import DatasetSummaryRecord


class DatasetSummaryRepository(Protocol):
    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord: ...

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None: ...

    def delete(self, dataset_name: str) -> None: ...

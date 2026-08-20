from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class DatasetAnalysisStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass
class DatasetSampleRecord:
    dataset_name: str
    sample_id: str
    razon_marcacion: str | None
    marcacion_final: str | None
    integration_point: str | None
    tipo: str | None
    triggered_rules: str | None


@dataclass
class DatasetSummaryRecord:
    dataset_name: str
    status: DatasetAnalysisStatus
    total_rows: int
    # field -> value -> count. Percentages are derived from these counts at
    # read time (see get_dataset_summary.py) rather than stored, so they
    # never drift from total_rows.
    field_distributions: dict[str, dict[str, int]] = field(default_factory=dict)
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None


class DatasetSampleRepository(Protocol):
    def create_batch(self, samples: list[DatasetSampleRecord]) -> None:
        ...

    def list_by_dataset(self, dataset_name: str) -> list[DatasetSampleRecord]:
        ...

    def delete_by_dataset(self, dataset_name: str) -> None:
        ...


class DatasetSummaryRepository(Protocol):
    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        ...

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        ...

    def delete(self, dataset_name: str) -> None:
        ...

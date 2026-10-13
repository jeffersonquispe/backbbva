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


class DatasetOrigin(StrEnum):
    """How a dataset came to exist. Orthogonal to DatasetAnalysisStatus,
    which tracks the analysis lifecycle, not provenance. Records how a
    dataset started, not an exhaustive ingestion history — a dataset can
    receive rows from multiple origins over its life via progressive fill.
    """

    UPLOADED = "UPLOADED"
    EMPTY = "EMPTY"
    EXTRACTED = "EXTRACTED"
    ALERT_CURATED = "ALERT_CURATED"


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
    # Complete dataset column catalog. Kept separate from distributions so
    # high-cardinality fields (ids, JSON history, timestamps) can appear in
    # model field selectors without bloating the DynamoDB summary item.
    available_fields: list[str] = field(default_factory=list)
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    origin: DatasetOrigin = DatasetOrigin.UPLOADED
    # Populated only when origin is EXTRACTED — the dataset(s) rows were
    # sampled from.
    source_dataset_names: list[str] = field(default_factory=list)
    # Populated only when origin is EXTRACTED — the field=value filters the
    # source rows were narrowed by before sampling.
    extraction_filter: dict[str, str] | None = None
    fraud_marking_analysis: dict | None = None
    fraud_marking_analysis_config: dict | None = None


class DatasetSampleRepository(Protocol):
    def create_batch(self, samples: list[DatasetSampleRecord]) -> None: ...

    def list_by_dataset(self, dataset_name: str) -> list[DatasetSampleRecord]: ...

    def delete_by_dataset(self, dataset_name: str) -> None: ...


class DatasetSummaryRepository(Protocol):
    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord: ...

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None: ...

    def delete(self, dataset_name: str) -> None: ...

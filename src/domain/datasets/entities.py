from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DatasetAnalysisStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


class DatasetOrigin(StrEnum):
    """How a dataset was first created; later appends may have other sources."""

    UPLOADED = "UPLOADED"
    EMPTY = "EMPTY"
    EXTRACTED = "EXTRACTED"
    ALERT_CURATED = "ALERT_CURATED"


@dataclass
class DatasetRecord:
    name: str
    row_count: int


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
    # Counts are the source of truth; percentages are derived from them.
    field_distributions: dict[str, dict[str, int]] = field(default_factory=dict)
    # Kept separate from distributions so high-cardinality columns remain
    # available to selectors without inflating the analysis summary.
    available_fields: list[str] = field(default_factory=list)
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    origin: DatasetOrigin = DatasetOrigin.UPLOADED
    # Used when this dataset was extracted from one or more source datasets.
    source_dataset_names: list[str] = field(default_factory=list)
    extraction_filter: dict[str, str] | None = None
    fraud_marking_analysis: dict[str, Any] | None = None
    fraud_marking_analysis_config: dict[str, Any] | None = None

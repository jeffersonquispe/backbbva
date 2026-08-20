from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.application.ports.dataset_analysis_port import DatasetAnalysisStatus


@dataclass
class UploadDatasetInput:
    name: str
    content: bytes


@dataclass
class UploadDatasetOutput:
    name: str
    status: DatasetAnalysisStatus


@dataclass
class FieldValueCount:
    value: str
    count: int
    percentage: float


@dataclass
class DatasetSummaryOutput:
    dataset_name: str
    status: DatasetAnalysisStatus
    total_rows: int
    field_distributions: dict[str, list[FieldValueCount]] = field(default_factory=dict)
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None

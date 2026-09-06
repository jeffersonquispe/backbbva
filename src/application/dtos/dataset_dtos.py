from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
)


@dataclass
class UploadDatasetInput:
    name: str
    content: bytes


@dataclass
class UploadDatasetOutput:
    name: str
    status: DatasetAnalysisStatus


@dataclass
class CreateEmptyDatasetInput:
    name: str
    fields: list[str]


@dataclass
class CreateEmptyDatasetOutput:
    name: str
    status: DatasetAnalysisStatus


@dataclass
class ExtractDatasetInput:
    source_names: list[str]
    # AND-combined field=value filters, applied before sampling.
    filters: dict[str, str]
    percentage: float
    target_name: str


@dataclass
class ExtractDatasetOutput:
    name: str
    status: DatasetAnalysisStatus


@dataclass
class AppendDatasetRowsInput:
    name: str
    # Already-shaped rows (nested-dict form, same shape DatasetRepository.get_rows
    # returns) - the router/use-case layer that builds these from a CSV upload,
    # a spreadsheet form, an extraction, or (later) an alert is responsible for
    # producing this shape before calling the use case that wraps this DTO.
    rows: list[dict[str, Any]]


@dataclass
class AppendDatasetRowsOutput:
    name: str
    total_rows: int
    status: DatasetAnalysisStatus


@dataclass
class GetDatasetRowsInput:
    name: str
    offset: int = 0
    limit: int = 50


@dataclass
class GetDatasetRowsOutput:
    rows: list[dict[str, Any]]
    total: int


@dataclass
class GetDatasetTemplateOutput:
    filename: str
    content: str


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
    available_fields: list[str] = field(default_factory=list)
    uploaded_at: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    origin: DatasetOrigin = DatasetOrigin.UPLOADED
    source_dataset_names: list[str] = field(default_factory=list)
    extraction_filter: dict[str, str] | None = None

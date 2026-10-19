from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, BinaryIO
from uuid import UUID

from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
)


@dataclass
class UploadDatasetInput:
    name: str
    content: bytes | None = None
    file: BinaryIO | None = None


@dataclass
class UploadDatasetOutput:
    name: str
    status: DatasetAnalysisStatus
    async_operation_id: UUID | None = None


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
class FraudMaturationProfile:
    """Distribution of the time elapsed between a row's first and second
    fraud mark, across every row where both timestamp fields parsed and the
    second mark did not precede the first. All durations in days."""

    sample_size: int
    avg_days: float | None = None
    min_days: float | None = None
    max_days: float | None = None
    p95_days: float | None = None


@dataclass
class FraudMarkingAnalysisInput:
    dataset_name: str
    # Field holding the initial fraud mark, e.g. "razon_marcacion".
    first_mark_field: str
    # Field holding the final/confirmed fraud mark, e.g. "marcacion_final".
    second_mark_field: str
    # Field holding the timestamp of the first mark.
    first_mark_time_field: str
    # Field holding the timestamp of the second mark.
    second_mark_time_field: str
    # Values that mean "flagged as fraud" in either mark field, e.g.
    # ["risk", "risk-suspected"] - a mark counts as positive if it matches
    # ANY of these. A row moving between two of these (e.g.
    # "risk-suspected" -> "risk") is not a remark - see
    # FraudMarkingAnalysisOutput.properly_marked.
    positive_values: list[str]


@dataclass
class FraudMarkingAnalysisOutput:
    dataset_name: str
    # Rows where both first_mark_field and second_mark_field were present -
    # the population the counts below are drawn from.
    evaluated_rows: int
    # Rows missing either mark field, excluded from evaluated_rows.
    skipped_rows: int
    # first mark positive, second mark negative.
    false_positives: int
    # first mark negative, second mark positive.
    false_negatives: int
    # first and second mark agree they're positive, agree they're negative,
    # or both land in positive_values but under different specific labels
    # (e.g. "risk-suspected" -> "risk") - not a real remark, just the case
    # escalating within the positive class, so it isn't a false anything.
    properly_marked: int
    maturation: FraudMaturationProfile


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
    fraud_marking_analysis: dict | None = None
    fraud_marking_analysis_config: dict | None = None

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
)


class DatasetResponse(BaseModel):
    name: str
    row_count: int


class UploadDatasetResponse(BaseModel):
    name: str
    status: DatasetAnalysisStatus
    async_operation_id: UUID | None = None


class StartDatasetUploadRequest(BaseModel):
    filename: str = Field(min_length=5, max_length=184)
    total_size_bytes: int = Field(ge=1)


class DatasetUploadSessionResponse(BaseModel):
    upload_id: UUID
    name: str
    part_size_bytes: int
    total_parts: int
    expires_at: datetime


class DeleteDatasetResponse(BaseModel):
    name: str
    deleted: bool
    async_operation_id: UUID | None = None


class FieldDistributionResponse(BaseModel):
    value: str
    count: int
    percentage: float


class FraudMaturationProfileResponse(BaseModel):
    sample_size: int
    avg_days: float | None
    min_days: float | None
    max_days: float | None
    p50_days: float | None = None
    p75_days: float | None = None
    p90_days: float | None = None
    p95_days: float | None
    p98_days: float | None = None
    p99_days: float | None = None


class FraudMarkingAnalysisResponse(BaseModel):
    dataset_name: str
    evaluated_rows: int
    skipped_rows: int
    false_positives: int
    false_negatives: int
    properly_marked: int
    maturation: FraudMaturationProfileResponse


class FraudMarkingAnalysisQueuedResponse(BaseModel):
    dataset_name: str
    status: Literal["PENDING"] = "PENDING"
    async_operation_id: UUID


class DatasetSummaryResponse(BaseModel):
    dataset_name: str
    status: DatasetAnalysisStatus
    total_rows: int
    field_distributions: dict[str, list[FieldDistributionResponse]]
    available_fields: list[str]
    uploaded_at: datetime | None
    updated_at: datetime | None
    error: str | None
    origin: DatasetOrigin
    source_dataset_names: list[str]
    extraction_filter: dict[str, str] | None
    fraud_marking_analysis: FraudMarkingAnalysisResponse | None = None
    split_metadata: dict[str, Any] | None = None


class CreateEmptyDatasetRequest(BaseModel):
    name: str = Field(..., min_length=1)
    fields: list[str] = Field(..., min_length=1)


class ExtractDatasetRequest(BaseModel):
    source_names: list[str] = Field(..., min_length=1)
    filters: dict[str, str] = Field(default_factory=dict)
    percentage: float = Field(..., gt=0, le=100)
    target_name: str = Field(..., min_length=1)


class PrepareDatasetSplitRequest(BaseModel):
    target_name: str = Field(..., min_length=1, max_length=184)
    proportions: dict[Literal["training", "validation", "calibration", "test"], float] = Field(
        default_factory=lambda: {
            "training": 0.6,
            "validation": 0.2,
            "calibration": 0.1,
            "test": 0.1,
        }
    )
    seed: int = 42
    stratify_fields: list[str] = Field(default_factory=list, max_length=20)


class PreviewDatasetSplitRequest(BaseModel):
    proportions: dict[Literal["training", "validation", "calibration", "test"], float] = Field(
        default_factory=lambda: {
            "training": 0.6,
            "validation": 0.2,
            "calibration": 0.1,
            "test": 0.1,
        }
    )
    seed: int = 42
    stratify_fields: list[str] = Field(default_factory=list, max_length=20)


class PreviewDatasetSplitResponse(BaseModel):
    source_dataset_name: str
    source_content_sha256: str
    source_row_count: int
    partition_counts: dict[str, int]
    proportions: dict[str, float]
    seed: int
    stratify_fields: list[str]
    available_fields: list[str]


class PrepareDatasetSplitResponse(BaseModel):
    dataset_name: str
    snapshot_id: str
    source_content_sha256: str
    partition_field: str
    partition_counts: dict[str, int]
    proportions: dict[str, float]
    seed: int
    stratify_fields: list[str]


class AppendDatasetRowsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(..., min_length=1)


class AppendDatasetRowsResponse(BaseModel):
    name: str
    total_rows: int
    status: DatasetAnalysisStatus


class DatasetRowsResponse(BaseModel):
    rows: list[dict[str, Any]]
    total: int


class CurateAlertToDatasetRequest(BaseModel):
    dataset_name: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=1)
    # Manual override of the configuration/version this curation's
    # Feedback record attributes to - when omitted, the use case tries to
    # auto-detect it from the alert's own workflow execution, and raises
    # ValueError (mapped to 400 below) if neither is available.
    configuration_id: str | None = None
    version: int | None = None


class CurateAlertToDatasetResponse(BaseModel):
    dataset_name: str
    total_rows: int
    status: DatasetAnalysisStatus
    feedback_id: UUID
    configuration_id: str
    version: int


class AlertFieldMappingResponse(BaseModel):
    dataset_name: str
    schema_version: int | None
    mappings: dict[str, str]
    updated_at: datetime | None


class SaveAlertFieldMappingRequest(BaseModel):
    schema_version: int
    mappings: dict[str, str]

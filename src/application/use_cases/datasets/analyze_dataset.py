from __future__ import annotations

from datetime import datetime, timezone

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSampleRecord,
    DatasetSampleRepository,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.field_extraction import (
    ANALYSIS_FIELDS,
    compute_distributions,
    discover_fields,
    extract_fields,
)


class AnalyzeDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        sample_repository: DatasetSampleRepository,
        summary_repository: DatasetSummaryRepository,
    ) -> None:
        self._datasets = dataset_repository
        self._samples = sample_repository
        self._summaries = summary_repository

    def execute(self, dataset_name: str) -> None:
        existing = self._summaries.get(dataset_name)
        uploaded_at = existing.uploaded_at if existing else None
        # Provenance is set once at creation (create_empty/extract_dataset/
        # upload) and must survive every subsequent re-analysis - it's not
        # something this use case computes.
        origin = existing.origin if existing else DatasetOrigin.UPLOADED
        source_dataset_names = existing.source_dataset_names if existing else []
        extraction_filter = existing.extraction_filter if existing else None
        try:
            rows = self._datasets.get_rows(dataset_name)
            samples = [
                DatasetSampleRecord(
                    dataset_name=dataset_name,
                    sample_id=str(index).zfill(8),
                    **extract_fields(row),
                )
                for index, row in enumerate(rows)
            ]
            self._samples.delete_by_dataset(dataset_name)
            if samples:
                self._samples.create_batch(samples)
            distributions = compute_distributions(rows, ANALYSIS_FIELDS)
            get_fields = getattr(self._datasets, "get_fields", None)
            available_fields = (
                get_fields(dataset_name) if callable(get_fields) else None
            )
            if not isinstance(available_fields, list):
                available_fields = discover_fields(rows)
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.READY,
                    total_rows=len(rows),
                    field_distributions=distributions,
                    available_fields=available_fields,
                    uploaded_at=uploaded_at,
                    updated_at=datetime.now(timezone.utc),
                    origin=origin,
                    source_dataset_names=source_dataset_names,
                    extraction_filter=extraction_filter,
                )
            )
        except Exception as exc:
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.FAILED,
                    total_rows=0,
                    field_distributions={},
                    uploaded_at=uploaded_at,
                    updated_at=datetime.now(timezone.utc),
                    error=str(exc),
                    origin=origin,
                    source_dataset_names=source_dataset_names,
                    extraction_filter=extraction_filter,
                )
            )
            raise

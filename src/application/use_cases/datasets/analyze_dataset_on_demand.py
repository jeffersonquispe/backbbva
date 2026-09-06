from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.dataset_dtos import UploadDatasetOutput
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)


class AnalyzeDatasetOnDemandUseCase:
    """Lets an analyst manually refresh a dataset's distributions after
    progressive-fill appends, without re-uploading - today analysis only
    ever runs automatically on upload."""

    def __init__(
        self,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
    ) -> None:
        self._summaries = summary_repository
        self._dispatcher = dispatcher

    def execute(self, dataset_name: str) -> UploadDatasetOutput:
        existing = self._summaries.get(dataset_name)
        now = datetime.now(timezone.utc)
        if existing is not None:
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.PENDING,
                    total_rows=existing.total_rows,
                    field_distributions=existing.field_distributions,
                    available_fields=existing.available_fields,
                    uploaded_at=existing.uploaded_at,
                    updated_at=now,
                    error=existing.error,
                    origin=existing.origin,
                    source_dataset_names=existing.source_dataset_names,
                    extraction_filter=existing.extraction_filter,
                )
            )
        else:
            # Defensive - shouldn't normally happen since every dataset
            # gets a summary at creation.
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.PENDING,
                    total_rows=0,
                    field_distributions={},
                )
            )
        self._dispatcher.dispatch(dataset_name)
        return UploadDatasetOutput(
            name=dataset_name, status=DatasetAnalysisStatus.PENDING
        )

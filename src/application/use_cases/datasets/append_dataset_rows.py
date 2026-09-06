from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.dataset_dtos import (
    AppendDatasetRowsInput,
    AppendDatasetRowsOutput,
)
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository


class AppendDatasetRowsUseCase:
    """Convergence point for "shape rows, then append" flows (CSV re-upload,
    manual spreadsheet-style entry, and future flows) - takes already-shaped
    list[dict] rows and doesn't care where they came from."""

    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher

    def execute(self, input: AppendDatasetRowsInput) -> AppendDatasetRowsOutput:
        new_total = self._datasets.append_rows(input.name, input.rows)

        existing = self._summaries.get(input.name)
        now = datetime.now(timezone.utc)
        uploaded_at = existing.uploaded_at if existing else now
        # Provenance is set once at creation and must survive every
        # subsequent write - it's not something this use case computes.
        origin = existing.origin if existing else DatasetOrigin.UPLOADED
        source_dataset_names = existing.source_dataset_names if existing else []
        extraction_filter = existing.extraction_filter if existing else None

        self._summaries.upsert(
            DatasetSummaryRecord(
                dataset_name=input.name,
                status=DatasetAnalysisStatus.PENDING,
                total_rows=new_total,
                field_distributions=(
                    existing.field_distributions if existing else {}
                ),
                available_fields=(existing.available_fields if existing else []),
                uploaded_at=uploaded_at,
                updated_at=now,
                origin=origin,
                source_dataset_names=source_dataset_names,
                extraction_filter=extraction_filter,
            )
        )
        self._dispatcher.dispatch(input.name)
        return AppendDatasetRowsOutput(
            name=input.name,
            total_rows=new_total,
            status=DatasetAnalysisStatus.PENDING,
        )

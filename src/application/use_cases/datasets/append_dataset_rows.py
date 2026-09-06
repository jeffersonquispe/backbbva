from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


def append_rows_and_dispatch(
    *,
    dataset_repository: DatasetRepository,
    summary_repository: DatasetSummaryRepository,
    dispatcher: DatasetAnalysisDispatcher,
    name: str,
    rows: list[dict[str, Any]],
) -> AppendDatasetRowsOutput:
    """Shared core of "append rows to an existing dataset, then re-analyze" -
    a plain function (not a use case another use case would depend on, per
    this codebase's "use cases orchestrate via ports only" rule) so both
    AppendDatasetRowsUseCase and curate_alert_to_dataset.py can reuse it by
    taking the same ports themselves, without one use case wrapping another."""
    new_total = dataset_repository.append_rows(name, rows)

    existing = summary_repository.get(name)
    now = datetime.now(timezone.utc)
    uploaded_at = existing.uploaded_at if existing else now
    # Provenance is set once at creation and must survive every
    # subsequent write - it's not something this function computes.
    origin = existing.origin if existing else DatasetOrigin.UPLOADED
    source_dataset_names = existing.source_dataset_names if existing else []
    extraction_filter = existing.extraction_filter if existing else None

    summary_repository.upsert(
        DatasetSummaryRecord(
            dataset_name=name,
            status=DatasetAnalysisStatus.PENDING,
            total_rows=new_total,
            field_distributions=(existing.field_distributions if existing else {}),
            available_fields=(existing.available_fields if existing else []),
            uploaded_at=uploaded_at,
            updated_at=now,
            origin=origin,
            source_dataset_names=source_dataset_names,
            extraction_filter=extraction_filter,
        )
    )
    dispatcher.dispatch(name)
    return AppendDatasetRowsOutput(
        name=name,
        total_rows=new_total,
        status=DatasetAnalysisStatus.PENDING,
    )


class AppendDatasetRowsUseCase:
    """Convergence point for "shape rows, then append" flows (CSV re-upload,
    manual spreadsheet-style entry, and alert curation) - takes already-shaped
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
        return append_rows_and_dispatch(
            dataset_repository=self._datasets,
            summary_repository=self._summaries,
            dispatcher=self._dispatcher,
            name=input.name,
            rows=input.rows,
        )

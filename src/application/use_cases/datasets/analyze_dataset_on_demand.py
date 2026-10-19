from __future__ import annotations

from src.application.dtos.dataset_dtos import UploadDatasetOutput
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.datasets.entities import DatasetAnalysisStatus, DatasetSummaryRecord


class AnalyzeDatasetOnDemandUseCase:
    """Lets an analyst manually refresh a dataset's distributions after
    progressive-fill appends, without re-uploading - today analysis only
    ever runs automatically on upload."""

    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
        async_operation_repository: AsyncOperationRepository | None = None,

        clock: Clock | None = None,
        id_generator: IdGenerator | None = None
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher
        self._operations = async_operation_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, dataset_name: str) -> UploadDatasetOutput:
        # Raises FileNotFoundError for a nonexistent dataset - checked before
        # touching the summary so a typo'd/deleted name can't leave behind a
        # phantom PENDING summary record for a dataset that was never created.
        self._datasets.get_fields(dataset_name)
        existing = self._summaries.get(dataset_name)
        now = self._clock.now()
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
        operation_id = None
        if self._operations is not None:
            operation_id = self._id_generator.new_id()
            self._operations.create(
                AsyncOperationRecord(
                    id=operation_id,
                    operation_type="dataset.analyze",
                    status=AsyncOperationStatus.PENDING,
                    payload={"dataset_name": dataset_name},
                    result={"stage": "queued", "progress_pct": 0},
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._dispatcher.dispatch(dataset_name, operation_id)
            self._operations.update(operation_id, status=AsyncOperationStatus.DISPATCHED)
        else:
            self._dispatcher.dispatch(dataset_name)
        return UploadDatasetOutput(
            name=dataset_name,
            status=DatasetAnalysisStatus.PENDING,
            async_operation_id=operation_id,
        )

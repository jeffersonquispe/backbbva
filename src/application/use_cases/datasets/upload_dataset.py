from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.dataset_dtos import UploadDatasetInput, UploadDatasetOutput
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository


class UploadDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher

    def execute(self, input: UploadDatasetInput) -> UploadDatasetOutput:
        # Writes via DatasetRepository (not ObjectStoragePort directly) so the
        # upload always lands wherever list()/get_rows()/delete() will look for
        # it - those already switch on DATASET_STORAGE_BACKEND, and previously
        # uploads bypassed that switch by always writing straight to MinIO.
        self._datasets.create_from_csv_bytes(input.name, input.content)
        now = datetime.now(timezone.utc)
        self._summaries.upsert(
            DatasetSummaryRecord(
                dataset_name=input.name,
                status=DatasetAnalysisStatus.PENDING,
                total_rows=0,
                field_distributions={},
                uploaded_at=now,
                updated_at=now,
            )
        )
        self._dispatcher.dispatch(input.name)
        return UploadDatasetOutput(name=input.name, status=DatasetAnalysisStatus.PENDING)

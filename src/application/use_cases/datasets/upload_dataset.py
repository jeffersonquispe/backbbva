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
from src.application.ports.object_storage_port import ObjectStoragePort


class UploadDatasetUseCase:
    def __init__(
        self,
        object_storage: ObjectStoragePort,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
    ) -> None:
        self._object_storage = object_storage
        self._summaries = summary_repository
        self._dispatcher = dispatcher

    def execute(self, input: UploadDatasetInput) -> UploadDatasetOutput:
        self._object_storage.put_bytes(
            key=f"{input.name}.csv",
            content=input.content,
            content_type="text/csv",
        )
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

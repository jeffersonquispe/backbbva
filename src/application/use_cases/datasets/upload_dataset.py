from __future__ import annotations

from datetime import datetime, timezone
import uuid

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
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)


class UploadDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
        async_operation_repository: AsyncOperationRepository | None = None,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher
        self._operations = async_operation_repository

    def execute(self, input: UploadDatasetInput) -> UploadDatasetOutput:
        # Writes via DatasetRepository (not ObjectStoragePort directly) so the
        # upload always lands wherever list()/get_rows()/delete() will look for
        # it - those already switch on DATASET_STORAGE_BACKEND, and previously
        # uploads bypassed that switch by always writing straight to MinIO.
        if input.file is not None:
            self._datasets.create_from_csv_file(input.name, input.file)
        elif input.content is not None:
            self._datasets.create_from_csv_bytes(input.name, input.content)
        else:
            raise ValueError("Either file or content is required")
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
        operation_id = None
        if self._operations is not None:
            operation_id = uuid.uuid4()
            self._operations.create(AsyncOperationRecord(
                id=operation_id, operation_type="dataset.analyze",
                status=AsyncOperationStatus.PENDING,
                payload={"dataset_name": input.name}, result=None, error=None,
                created_at=now, updated_at=now,
            ))
        if operation_id is None:
            self._dispatcher.dispatch(input.name)
        else:
            self._dispatcher.dispatch(input.name, operation_id)
        if operation_id is not None:
            self._operations.update(operation_id, status=AsyncOperationStatus.DISPATCHED)
        return UploadDatasetOutput(
            name=input.name, status=DatasetAnalysisStatus.PENDING,
            async_operation_id=operation_id,
        )

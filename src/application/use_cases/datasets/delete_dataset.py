from __future__ import annotations

from datetime import datetime, timezone
import uuid

from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.dataset_analysis_port import (
    DatasetSampleRepository,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository


class DeleteDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        sample_repository: DatasetSampleRepository,
        summary_repository: DatasetSummaryRepository,
        async_operation_repository: AsyncOperationRepository | None = None,
    ) -> None:
        self._datasets = dataset_repository
        self._samples = sample_repository
        self._summaries = summary_repository
        self._operations = async_operation_repository

    def schedule(self, dataset_name: str) -> uuid.UUID | None:
        """Create the durable tracker used by the Celery deletion task."""
        if self._operations is None:
            return None
        now = datetime.now(timezone.utc)
        operation_id = uuid.uuid4()
        self._operations.create(
            AsyncOperationRecord(
                id=operation_id,
                operation_type="dataset.delete",
                status=AsyncOperationStatus.PENDING,
                payload={"dataset_name": dataset_name},
                result={"stage": "queued", "progress_pct": 0},
                error=None,
                created_at=now,
                updated_at=now,
            )
        )
        return operation_id

    def execute(self, dataset_name: str) -> None:
        self._datasets.delete(dataset_name)
        self._samples.delete_by_dataset(dataset_name)
        self._summaries.delete(dataset_name)

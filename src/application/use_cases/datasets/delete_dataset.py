from __future__ import annotations

import uuid

from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationRepository,
    AsyncOperationStatus,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_analysis_port import DatasetSampleRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.ports.id_generator_port import IdGenerator
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class DeleteDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        sample_repository: DatasetSampleRepository,
        summary_repository: DatasetSummaryRepository,
        async_operation_repository: AsyncOperationRepository | None = None,

        clock: Clock | None = None,
        id_generator: IdGenerator | None = None
    ) -> None:
        self._datasets = dataset_repository
        self._samples = sample_repository
        self._summaries = summary_repository
        self._operations = async_operation_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def schedule(self, dataset_name: str) -> uuid.UUID | None:
        """Create the durable tracker used by the Celery deletion task."""
        if self._operations is None:
            return None
        now = self._clock.now()
        operation_id = self._id_generator.new_id()
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

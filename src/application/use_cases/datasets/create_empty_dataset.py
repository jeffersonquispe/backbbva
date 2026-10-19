from __future__ import annotations

from src.application.dtos.dataset_dtos import (
    CreateEmptyDatasetInput,
    CreateEmptyDatasetOutput,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_analysis_port import (
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.runtime_defaults import resolve_clock
from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)


class CreateEmptyDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,

        clock: Clock | None = None
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._clock = resolve_clock(clock)

    def execute(self, input: CreateEmptyDatasetInput) -> CreateEmptyDatasetOutput:
        self._datasets.create(input.name, input.fields)
        now = self._clock.now()
        self._summaries.upsert(
            DatasetSummaryRecord(
                dataset_name=input.name,
                status=DatasetAnalysisStatus.READY,
                total_rows=0,
                field_distributions={},
                available_fields=input.fields,
                uploaded_at=now,
                updated_at=now,
                origin=DatasetOrigin.EMPTY,
            )
        )
        return CreateEmptyDatasetOutput(name=input.name, status=DatasetAnalysisStatus.READY)

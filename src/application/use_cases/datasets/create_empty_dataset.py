from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.dataset_dtos import (
    CreateEmptyDatasetInput,
    CreateEmptyDatasetOutput,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository


class CreateEmptyDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository

    def execute(self, input: CreateEmptyDatasetInput) -> CreateEmptyDatasetOutput:
        self._datasets.create(input.name, input.fields)
        now = datetime.now(timezone.utc)
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

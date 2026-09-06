from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.dataset_dtos import ExtractDatasetInput, ExtractDatasetOutput
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
from src.application.use_cases.datasets.field_extraction import discover_fields
from src.application.use_cases.test_runs.dataset_sampling import (
    filter_rows,
    sample_percentage,
)


class ExtractDatasetUseCase:
    """Builds a new dataset by filtering + straight-percentage sampling the
    combined rows of one or more source datasets - "extract 5% of records
    where field A = X AND field B = Y" (no stratification, confirmed with
    the end user - see dataset_sampling.py's filter_rows/sample_percentage
    docstrings)."""

    def __init__(
        self,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher

    def execute(self, input: ExtractDatasetInput) -> ExtractDatasetOutput:
        rows = []
        for source_name in input.source_names:
            rows.extend(self._datasets.get_rows(source_name))

        filtered = filter_rows(rows, input.filters)
        sampled = sample_percentage(filtered, input.percentage)

        if not sampled:
            raise ValueError(
                f"No rows matched the given filters across {input.source_names}"
            )

        fields = discover_fields(sampled)

        self._datasets.create(input.target_name, fields)
        self._datasets.append_rows(input.target_name, sampled)

        now = datetime.now(timezone.utc)
        self._summaries.upsert(
            DatasetSummaryRecord(
                dataset_name=input.target_name,
                status=DatasetAnalysisStatus.PENDING,
                total_rows=0,
                field_distributions={},
                uploaded_at=now,
                updated_at=now,
                origin=DatasetOrigin.EXTRACTED,
                source_dataset_names=input.source_names,
                extraction_filter=input.filters,
            )
        )
        self._dispatcher.dispatch(input.target_name)
        return ExtractDatasetOutput(
            name=input.target_name, status=DatasetAnalysisStatus.PENDING
        )

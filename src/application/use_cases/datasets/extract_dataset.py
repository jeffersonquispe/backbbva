from __future__ import annotations

from src.application.dtos.dataset_dtos import ExtractDatasetInput, ExtractDatasetOutput
from src.application.errors import ValidationError
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.datasets.field_extraction import discover_fields
from src.application.use_cases.test_runs.dataset_sampling import (
    filter_rows,
    sample_percentage,
)
from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
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

        clock: Clock | None = None
    ) -> None:
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher
        self._clock = resolve_clock(clock)

    def execute(self, input: ExtractDatasetInput) -> ExtractDatasetOutput:
        rows = []
        for source_name in input.source_names:
            rows.extend(self._datasets.get_rows(source_name))

        filtered = filter_rows(rows, input.filters)
        sampled = sample_percentage(filtered, input.percentage)

        if not sampled:
            raise ValidationError(
                f"No rows matched the given filters across {input.source_names}"
            )

        # Derived from the full filtered set, not just the sampled subset -
        # a sparsely-populated column can easily have zero non-null values
        # in whichever rows happened to be sampled, which would silently
        # drop that column from the new dataset's header entirely (not just
        # leave it blank) if discover_fields ran on `sampled` instead.
        fields = discover_fields(filtered)

        self._datasets.create(input.target_name, fields)
        self._datasets.append_rows(input.target_name, sampled)

        now = self._clock.now()
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

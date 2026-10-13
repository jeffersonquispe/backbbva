from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.runtime_defaults import DEFAULT_CLOCK, resolve_clock



from datetime import datetime, timezone
from collections import Counter
import random
from collections.abc import Callable

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSampleRecord,
    DatasetSampleRepository,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.field_extraction import (
    ANALYSIS_FIELDS,
    LIST_VALUED_FIELDS,
    compute_distributions,
    discover_fields,
    extract_fields,
    select_profiling_fields,
    split_list_value,
    UNKNOWN,
)


class AnalyzeDatasetUseCase:
    def __init__(
        self,
        dataset_repository: DatasetRepository,
        sample_repository: DatasetSampleRepository,
        summary_repository: DatasetSummaryRepository,
        max_input_bytes: int = 268435456,

        clock: Clock | None = None
    ) -> None:
        self._datasets = dataset_repository
        self._samples = sample_repository
        self._summaries = summary_repository
        self._max_input_bytes = max_input_bytes
        self._clock = resolve_clock(clock)

    def execute(
        self,
        dataset_name: str,
        progress: Callable[[dict], None] | None = None,
    ) -> None:
        existing = self._summaries.get(dataset_name)
        uploaded_at = existing.uploaded_at if existing else None
        # Provenance is set once at creation (create_empty/extract_dataset/
        # upload) and must survive every subsequent re-analysis - it's not
        # something this use case computes.
        origin = existing.origin if existing else DatasetOrigin.UPLOADED
        source_dataset_names = existing.source_dataset_names if existing else []
        extraction_filter = existing.extraction_filter if existing else None
        iter_rows = getattr(self._datasets, "iter_rows", None)
        if callable(iter_rows):
            self._analyze_streaming(
                dataset_name, iter_rows, uploaded_at, origin,
                source_dataset_names, extraction_filter, progress,
            )
            return
        get_size = getattr(self._datasets, "get_size", None)
        input_size = get_size(dataset_name) if callable(get_size) else None
        if isinstance(input_size, int) and input_size > self._max_input_bytes:
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.FAILED,
                    total_rows=0,
                    field_distributions={},
                    uploaded_at=uploaded_at,
                    updated_at=self._clock.now(),
                    error=(
                        f"Dataset is {input_size} bytes; automatic analysis is limited "
                        f"to {self._max_input_bytes} bytes to protect the worker"
                    ),
                    origin=origin,
                    source_dataset_names=source_dataset_names,
                    extraction_filter=extraction_filter,
                )
            )
            return
        try:
            rows = self._datasets.get_rows(dataset_name)
            samples = [
                DatasetSampleRecord(
                    dataset_name=dataset_name,
                    sample_id=str(index).zfill(8),
                    **extract_fields(row),
                )
                for index, row in enumerate(rows)
            ]
            self._samples.delete_by_dataset(dataset_name)
            if samples:
                self._samples.create_batch(samples)
            get_fields = getattr(self._datasets, "get_fields", None)
            available_fields = (
                get_fields(dataset_name) if callable(get_fields) else None
            )
            if not isinstance(available_fields, list):
                available_fields = discover_fields(rows)
            distributions = compute_distributions(
                rows, select_profiling_fields(rows, available_fields)
            )
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.READY,
                    total_rows=len(rows),
                    field_distributions=distributions,
                    available_fields=available_fields,
                    uploaded_at=uploaded_at,
                    updated_at=self._clock.now(),
                    origin=origin,
                    source_dataset_names=source_dataset_names,
                    extraction_filter=extraction_filter,
                )
            )
        except Exception as exc:
            self._summaries.upsert(
                DatasetSummaryRecord(
                    dataset_name=dataset_name,
                    status=DatasetAnalysisStatus.FAILED,
                    total_rows=0,
                    field_distributions={},
                    uploaded_at=uploaded_at,
                    updated_at=self._clock.now(),
                    error=str(exc),
                    origin=origin,
                    source_dataset_names=source_dataset_names,
                    extraction_filter=extraction_filter,
                )
            )
            raise

    def _analyze_streaming(
        self, dataset_name, iter_rows, uploaded_at, origin, source_dataset_names,
        extraction_filter, progress
    ) -> None:
        """Profile MinIO CSVs in one pass with bounded memory."""
        self._samples.delete_by_dataset(dataset_name)
        # A byte-based bar lies for CSVs with large JSON cells.  Count CSV
        # records with the same parser first, then use that exact total for
        # the analysis pass.  Both passes stream from storage, so RAM stays
        # bounded regardless of the dataset size.
        if progress is not None:
            progress({"stage": "counting_rows", "progress_pct": 0})
        expected_rows = sum(1 for _ in iter_rows(dataset_name))
        if progress is not None:
            progress({
                "stage": "streaming_rows",
                "progress_pct": 0,
                "processed_rows": 0,
                "total_rows": expected_rows,
            })
        counters = {field: Counter() for field in ANALYSIS_FIELDS}
        sample_limit = 5_000
        samples: list[DatasetSampleRecord] = []
        randomizer = random.Random(dataset_name)
        total_rows = 0
        try:
            for row in iter_rows(dataset_name):
                extracted = extract_fields(row)
                sample = DatasetSampleRecord(
                    dataset_name=dataset_name,
                    sample_id=str(total_rows).zfill(8),
                    **extracted,
                )
                if len(samples) < sample_limit:
                    samples.append(sample)
                else:
                    # Reservoir sampling keeps a representative bounded
                    # sample without retaining every dataset row.
                    replacement_index = randomizer.randrange(total_rows + 1)
                    if replacement_index < sample_limit:
                        samples[replacement_index] = sample
                for field in ANALYSIS_FIELDS:
                    value = extracted[field]
                    if field in LIST_VALUED_FIELDS:
                        values = split_list_value(value) if value else []
                        for item in values or [UNKNOWN]:
                            counters[field][item] += 1
                    else:
                        counters[field][value or UNKNOWN] += 1
                total_rows += 1
                if progress is not None and total_rows % 10_000 == 0:
                    progress({
                        "stage": "streaming_rows",
                        # Reserve 100% for the persisted final result.
                        "progress_pct": min(99, int(total_rows * 100 / expected_rows))
                        if expected_rows else 99,
                        "processed_rows": total_rows,
                        "total_rows": expected_rows,
                    })
            if samples:
                for start in range(0, len(samples), 1_000):
                    self._samples.create_batch(samples[start : start + 1_000])
            get_fields = getattr(self._datasets, "get_fields", None)
            fields = get_fields(dataset_name) if callable(get_fields) else []
            self._summaries.upsert(DatasetSummaryRecord(
                dataset_name=dataset_name, status=DatasetAnalysisStatus.READY,
                total_rows=total_rows,
                field_distributions={field: dict(counter) for field, counter in counters.items()},
                available_fields=fields, uploaded_at=uploaded_at,
                updated_at=self._clock.now(), origin=origin,
                source_dataset_names=source_dataset_names,
                extraction_filter=extraction_filter,
            ))
            if progress is not None:
                progress({
                    "stage": "analysis_complete", "progress_pct": 100,
                    "processed_rows": total_rows, "total_rows": expected_rows,
                })
        except Exception as exc:
            self._summaries.upsert(DatasetSummaryRecord(
                dataset_name=dataset_name, status=DatasetAnalysisStatus.FAILED,
                total_rows=0, field_distributions={}, uploaded_at=uploaded_at,
                updated_at=self._clock.now(), error=str(exc), origin=origin,
                source_dataset_names=source_dataset_names,
                extraction_filter=extraction_filter,
            ))
            raise

from __future__ import annotations

from src.application.dtos.dataset_dtos import DatasetSummaryOutput, FieldValueCount
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.use_cases.datasets.field_extraction import discover_fields


class GetDatasetSummaryUseCase:
    def __init__(
        self,
        summary_repository: DatasetSummaryRepository,
        dataset_repository: DatasetRepository | None = None,
    ) -> None:
        self._summaries = summary_repository
        self._datasets = dataset_repository

    def execute(self, dataset_name: str) -> DatasetSummaryOutput | None:
        summary = self._summaries.get(dataset_name)
        if summary is None:
            return None
        total = summary.total_rows
        field_distributions = {
            field_name: [
                FieldValueCount(
                    value=value,
                    count=count,
                    percentage=round(count / total * 100, 2) if total else 0.0,
                )
                for value, count in sorted(counts.items(), key=lambda kv: -kv[1])
            ]
            for field_name, counts in summary.field_distributions.items()
        }
        available_fields = summary.available_fields
        # Summaries written before the column catalog was introduced have no
        # available_fields. Derive it read-only from the source dataset so
        # already-uploaded datasets immediately expose their complete schema.
        if not available_fields and self._datasets is not None:
            try:
                get_fields = getattr(self._datasets, "get_fields", None)
                discovered = get_fields(dataset_name) if callable(get_fields) else None
                if isinstance(discovered, list):
                    available_fields = discovered
                else:
                    available_fields = discover_fields(
                        self._datasets.get_rows(dataset_name)
                    )
            except Exception:
                # The statistical fields remain a useful compatibility
                # fallback if the source object is temporarily unavailable.
                available_fields = list(field_distributions)
        elif not available_fields:
            available_fields = list(field_distributions)
        return DatasetSummaryOutput(
            dataset_name=summary.dataset_name,
            status=summary.status,
            total_rows=total,
            field_distributions=field_distributions,
            available_fields=available_fields,
            uploaded_at=summary.uploaded_at,
            updated_at=summary.updated_at,
            error=summary.error,
            origin=summary.origin,
            source_dataset_names=summary.source_dataset_names,
            extraction_filter=summary.extraction_filter,
            fraud_marking_analysis=summary.fraud_marking_analysis,
            fraud_marking_analysis_config=summary.fraud_marking_analysis_config,
        )

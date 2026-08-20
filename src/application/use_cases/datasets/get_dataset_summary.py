from __future__ import annotations

from src.application.dtos.dataset_dtos import DatasetSummaryOutput, FieldValueCount
from src.application.ports.dataset_analysis_port import DatasetSummaryRepository


class GetDatasetSummaryUseCase:
    def __init__(self, summary_repository: DatasetSummaryRepository) -> None:
        self._summaries = summary_repository

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
        return DatasetSummaryOutput(
            dataset_name=summary.dataset_name,
            status=summary.status,
            total_rows=total,
            field_distributions=field_distributions,
            uploaded_at=summary.uploaded_at,
            updated_at=summary.updated_at,
            error=summary.error,
        )

from __future__ import annotations

from datetime import datetime, timezone

from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.use_cases.datasets.analyze_dataset_on_demand import (
    AnalyzeDatasetOnDemandUseCase,
)


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, DatasetSummaryRecord] = {}

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._by_name[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._by_name.get(dataset_name)

    def delete(self, dataset_name: str) -> None:
        self._by_name.pop(dataset_name, None)


class RecordingDatasetAnalysisDispatcher(DatasetAnalysisDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, dataset_name: str) -> None:
        self.dispatched.append(dataset_name)


def test_analyze_dataset_on_demand_preserves_existing_summary_fields() -> None:
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    original_uploaded_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    original_updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    summaries.upsert(
        DatasetSummaryRecord(
            dataset_name="ds1",
            status=DatasetAnalysisStatus.READY,
            total_rows=42,
            field_distributions={"field": {"v": 42}},
            available_fields=["field", "other"],
            uploaded_at=original_uploaded_at,
            updated_at=original_updated_at,
            error=None,
            origin=DatasetOrigin.EXTRACTED,
            source_dataset_names=["source_a"],
            extraction_filter={"tipo": "fraud"},
        )
    )
    use_case = AnalyzeDatasetOnDemandUseCase(
        summary_repository=summaries, dispatcher=dispatcher
    )

    output = use_case.execute("ds1")

    assert output.name == "ds1"
    assert output.status == DatasetAnalysisStatus.PENDING

    summary = summaries.get("ds1")
    assert summary is not None
    assert summary.status == DatasetAnalysisStatus.PENDING
    assert summary.updated_at != original_updated_at
    # Every other field carried over unchanged.
    assert summary.total_rows == 42
    assert summary.field_distributions == {"field": {"v": 42}}
    assert summary.available_fields == ["field", "other"]
    assert summary.uploaded_at == original_uploaded_at
    assert summary.origin == DatasetOrigin.EXTRACTED
    assert summary.source_dataset_names == ["source_a"]
    assert summary.extraction_filter == {"tipo": "fraud"}

    assert dispatcher.dispatched == ["ds1"]


def test_analyze_dataset_on_demand_with_no_existing_summary_creates_minimal_pending() -> None:
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = AnalyzeDatasetOnDemandUseCase(
        summary_repository=summaries, dispatcher=dispatcher
    )

    output = use_case.execute("brand_new")

    assert output.name == "brand_new"
    assert output.status == DatasetAnalysisStatus.PENDING

    summary = summaries.get("brand_new")
    assert summary is not None
    assert summary.status == DatasetAnalysisStatus.PENDING
    assert summary.total_rows == 0
    assert summary.field_distributions == {}
    assert summary.available_fields == []
    assert summary.origin == DatasetOrigin.UPLOADED
    assert summary.source_dataset_names == []
    assert summary.extraction_filter is None

    assert dispatcher.dispatched == ["brand_new"]

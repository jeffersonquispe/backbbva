from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.use_cases.datasets.analyze_dataset_on_demand import (
    AnalyzeDatasetOnDemandUseCase,
)


class InMemoryDatasetRepository(DatasetRepository):
    def __init__(self, existing_names: set[str]) -> None:
        self._existing_names = existing_names

    def list(self):
        return []

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return []

    def get_fields(self, name: str) -> list[str]:
        if name not in self._existing_names:
            raise FileNotFoundError(name)
        return []

    def get_rows_page(self, name: str, offset: int, limit: int):
        return [], 0

    def create(self, name: str, fields: list[str]) -> None:
        pass

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        pass

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        return 0

    def delete(self, name: str) -> None:
        pass


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


class OperationAwareDispatcher(DatasetAnalysisDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, Any]] = []

    def dispatch(self, dataset_name: str, operation_id=None) -> None:
        self.dispatched.append((dataset_name, operation_id))


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations = {}

    def create(self, operation):
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id):
        return self.operations.get(operation_id)

    def update(self, operation_id, **changes):
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        updated = replace(operation, **changes)
        self.operations[operation_id] = updated
        return updated

    def list(self, status=None, limit=100):
        return list(self.operations.values())[:limit]

    def list_active(self, limit=100):
        return []

    def delete(self, operation_id):
        self.operations.pop(operation_id, None)


def test_analyze_dataset_on_demand_preserves_existing_summary_fields() -> None:
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    original_uploaded_at = datetime(2026, 1, 1, tzinfo=UTC)
    original_updated_at = datetime(2026, 1, 2, tzinfo=UTC)
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
        dataset_repository=InMemoryDatasetRepository(existing_names={"ds1"}),
        summary_repository=summaries,
        dispatcher=dispatcher,
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


def test_analyze_dataset_on_demand_with_no_existing_summary_creates_minimal_pending() -> (
    None
):
    # Dataset exists in storage but has no DynamoDB summary yet (defensive
    # path - shouldn't normally happen since every dataset gets a summary at
    # creation, but this must not crash if it does).
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = AnalyzeDatasetOnDemandUseCase(
        dataset_repository=InMemoryDatasetRepository(existing_names={"brand_new"}),
        summary_repository=summaries,
        dispatcher=dispatcher,
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


def test_analyze_dataset_on_demand_returns_the_operation_it_dispatched() -> None:
    operations = InMemoryAsyncOperationRepository()
    dispatcher = OperationAwareDispatcher()
    use_case = AnalyzeDatasetOnDemandUseCase(
        dataset_repository=InMemoryDatasetRepository(existing_names={"ds"}),
        summary_repository=InMemoryDatasetSummaryRepository(),
        dispatcher=dispatcher,
        async_operation_repository=operations,
    )

    output = use_case.execute("ds")

    assert output.async_operation_id is not None
    assert dispatcher.dispatched == [("ds", output.async_operation_id)]
    operation = operations.get(output.async_operation_id)
    assert operation is not None
    assert operation.operation_type == "dataset.analyze"
    assert operation.status == AsyncOperationStatus.DISPATCHED


def test_analyze_dataset_on_demand_raises_file_not_found_for_nonexistent_dataset() -> (
    None
):
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = AnalyzeDatasetOnDemandUseCase(
        dataset_repository=InMemoryDatasetRepository(existing_names=set()),
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(FileNotFoundError):
        use_case.execute("ghost")

    assert summaries.get("ghost") is None
    assert dispatcher.dispatched == []

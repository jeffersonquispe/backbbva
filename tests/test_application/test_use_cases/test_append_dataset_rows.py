from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from src.application.dtos.dataset_dtos import AppendDatasetRowsInput
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
from src.application.use_cases.datasets.append_dataset_rows import (
    AppendDatasetRowsUseCase,
)


class FakeDatasetRepository(DatasetRepository):
    def __init__(self, new_total: int = 5, missing_name: str | None = None) -> None:
        self.new_total = new_total
        self.missing_name = missing_name
        self.append_calls: list[tuple[str, list[dict[str, Any]]]] = []

    def list(self):
        return []

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return []

    def get_fields(self, name: str) -> list[str]:
        return []

    def get_rows_page(self, name: str, offset: int, limit: int):
        return [], 0

    def create(self, name: str, fields: list[str]) -> None:
        pass

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        if self.missing_name is not None and name == self.missing_name:
            raise FileNotFoundError(name)
        self.append_calls.append((name, rows))
        return self.new_total

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


def test_append_dataset_rows_with_no_prior_summary_uses_defaults() -> None:
    datasets = FakeDatasetRepository(new_total=3)
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = AppendDatasetRowsUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        AppendDatasetRowsInput(name="ds1", rows=[{"a": "1"}, {"a": "2"}])
    )

    assert output.name == "ds1"
    assert output.total_rows == 3
    assert output.status == DatasetAnalysisStatus.PENDING
    assert datasets.append_calls == [("ds1", [{"a": "1"}, {"a": "2"}])]

    summary = summaries.get("ds1")
    assert summary is not None
    assert summary.status == DatasetAnalysisStatus.PENDING
    assert summary.total_rows == 3
    assert summary.field_distributions == {}
    assert summary.available_fields == []
    assert summary.origin == DatasetOrigin.UPLOADED
    assert summary.source_dataset_names == []
    assert summary.extraction_filter is None
    assert summary.uploaded_at is not None

    assert dispatcher.dispatched == ["ds1"]


def test_append_dataset_rows_preserves_provenance_from_prior_summary() -> None:
    datasets = FakeDatasetRepository(new_total=10)
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    original_uploaded_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    summaries.upsert(
        DatasetSummaryRecord(
            dataset_name="ds2",
            status=DatasetAnalysisStatus.READY,
            total_rows=7,
            field_distributions={"field": {"v": 7}},
            available_fields=["field"],
            uploaded_at=original_uploaded_at,
            updated_at=original_uploaded_at,
            origin=DatasetOrigin.EXTRACTED,
            source_dataset_names=["source_a", "source_b"],
            extraction_filter={"tipo": "fraud"},
        )
    )
    use_case = AppendDatasetRowsUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        AppendDatasetRowsInput(name="ds2", rows=[{"field": "x"}])
    )

    assert output.total_rows == 10
    summary = summaries.get("ds2")
    assert summary is not None
    assert summary.status == DatasetAnalysisStatus.PENDING
    assert summary.total_rows == 10
    assert summary.origin == DatasetOrigin.EXTRACTED
    assert summary.source_dataset_names == ["source_a", "source_b"]
    assert summary.extraction_filter == {"tipo": "fraud"}
    assert summary.uploaded_at == original_uploaded_at
    # Prior field_distributions/available_fields preserved until re-analysis runs.
    assert summary.field_distributions == {"field": {"v": 7}}
    assert summary.available_fields == ["field"]

    assert dispatcher.dispatched == ["ds2"]


def test_append_dataset_rows_propagates_file_not_found_when_dataset_missing() -> None:
    datasets = FakeDatasetRepository(missing_name="ghost")
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = AppendDatasetRowsUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(FileNotFoundError):
        use_case.execute(AppendDatasetRowsInput(name="ghost", rows=[{"a": "1"}]))

    assert summaries.get("ghost") is None
    assert dispatcher.dispatched == []

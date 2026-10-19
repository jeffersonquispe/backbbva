from __future__ import annotations

from typing import Any

import pytest

from src.application.dtos.dataset_dtos import ExtractDatasetInput
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)
from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.use_cases.datasets.extract_dataset import ExtractDatasetUseCase


class InMemoryDatasetRepository(DatasetRepository):
    def __init__(self) -> None:
        self._rows: dict[str, list[dict[str, Any]]] = {}
        self._fields: dict[str, list[str]] = {}

    def seed(self, name: str, rows: list[dict[str, Any]]) -> None:
        self._rows[name] = list(rows)

    def list(self) -> list[DatasetRecord]:
        return [
            DatasetRecord(name=name, row_count=len(rows))
            for name, rows in self._rows.items()
        ]

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        if name not in self._rows:
            raise FileNotFoundError(name)
        return list(self._rows[name])

    def get_fields(self, name: str) -> list[str]:
        return self._fields.get(name, [])

    def get_rows_page(
        self, name: str, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.get_rows(name)
        return rows[offset : offset + limit], len(rows)

    def create(self, name: str, fields: list[str]) -> None:
        if name in self._rows:
            raise FileExistsError(name)
        self._rows[name] = []
        self._fields[name] = fields

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        if name not in self._rows:
            raise FileNotFoundError(name)
        self._rows[name].extend(rows)
        return len(self._rows[name])

    def delete(self, name: str) -> None:
        self._rows.pop(name, None)
        self._fields.pop(name, None)


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


def _rows(prefix: str, n: int, **extra: str) -> list[dict[str, Any]]:
    rows = []
    for i in range(n):
        row = {"id": f"{prefix}-{i}"}
        row.update(extra)
        rows.append(row)
    return rows


def test_extract_header_includes_columns_absent_from_the_sampled_subset() -> None:
    # A column sparsely populated across the filtered set can easily have
    # zero non-null values in whichever specific rows get randomly sampled -
    # the header must still include it (discover_fields on the full filtered
    # set, not just the sampled rows), or that column silently vanishes from
    # the new dataset entirely rather than just being blank for some rows.
    # 2 filtered rows, only one carrying "rare_flag", percentage=50 samples
    # exactly 1 of the 2 (round(2 * 0.5) == 1) - whichever one random.sample
    # picks, the header must still include "rare_flag" because it's derived
    # from the full filtered set, not the random 1-row sample.
    datasets = InMemoryDatasetRepository()
    rows = _rows("row", 2, region="north")
    rows[0]["rare_flag"] = "yes"
    datasets.seed("source_a", rows)
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = ExtractDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    use_case.execute(
        ExtractDatasetInput(
            source_names=["source_a"],
            filters={"region": "north"},
            percentage=50,
            target_name="extracted_sparse",
        )
    )

    assert "rare_flag" in datasets._fields["extracted_sparse"]


def test_extract_single_source_happy_path() -> None:
    datasets = InMemoryDatasetRepository()
    # 10 rows match the filter, 5 don't - 50% of 10 matching rows -> 5 sampled.
    datasets.seed(
        "source_a",
        _rows("match", 10, region="north", tipo="fraud")
        + _rows("nomatch", 5, region="south", tipo="fraud"),
    )
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = ExtractDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        ExtractDatasetInput(
            source_names=["source_a"],
            filters={"region": "north"},
            percentage=50,
            target_name="extracted_1",
        )
    )

    assert output.name == "extracted_1"
    assert output.status == DatasetAnalysisStatus.PENDING

    target_rows = datasets.get_rows("extracted_1")
    assert len(target_rows) == 5
    assert all(r["region"] == "north" for r in target_rows)

    summary = summaries.get("extracted_1")
    assert summary is not None
    assert summary.origin == DatasetOrigin.EXTRACTED
    assert summary.source_dataset_names == ["source_a"]
    assert summary.extraction_filter == {"region": "north"}
    assert summary.status == DatasetAnalysisStatus.PENDING

    assert dispatcher.dispatched == ["extracted_1"]


def test_extract_concatenates_multiple_sources_before_filtering() -> None:
    datasets = InMemoryDatasetRepository()
    datasets.seed("source_a", _rows("a", 4, region="north"))
    datasets.seed("source_b", _rows("b", 6, region="north"))
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = ExtractDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    output = use_case.execute(
        ExtractDatasetInput(
            source_names=["source_a", "source_b"],
            filters={"region": "north"},
            percentage=100,
            target_name="extracted_multi",
        )
    )

    target_rows = datasets.get_rows("extracted_multi")
    # 4 + 6 = 10 combined rows, all match, 100% sampled -> all 10 present.
    assert len(target_rows) == 10
    ids = {r["id"] for r in target_rows}
    assert ids == {f"a-{i}" for i in range(4)} | {f"b-{i}" for i in range(6)}
    assert output.name == "extracted_multi"
    summary = summaries.get("extracted_multi")
    assert summary.source_dataset_names == ["source_a", "source_b"]


def test_extract_with_empty_filters_matches_every_row() -> None:
    datasets = InMemoryDatasetRepository()
    datasets.seed("source_a", _rows("row", 20))
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = ExtractDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    use_case.execute(
        ExtractDatasetInput(
            source_names=["source_a"],
            filters={},
            percentage=50,
            target_name="extracted_all",
        )
    )

    # Empty filters match all 20 source rows; 50% sampled -> 10.
    assert len(datasets.get_rows("extracted_all")) == 10


def test_extract_raises_and_leaves_no_partial_dataset_when_nothing_matches() -> None:
    datasets = InMemoryDatasetRepository()
    datasets.seed("source_a", _rows("row", 5, region="south"))
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = ExtractDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(ValueError, match="No rows matched"):
        use_case.execute(
            ExtractDatasetInput(
                source_names=["source_a"],
                filters={"region": "north"},
                percentage=100,
                target_name="extracted_none",
            )
        )

    assert "extracted_none" not in {d.name for d in datasets.list()}
    assert summaries.get("extracted_none") is None
    assert dispatcher.dispatched == []


def test_extract_propagates_file_exists_error_when_target_name_taken() -> None:
    datasets = InMemoryDatasetRepository()
    datasets.seed("source_a", _rows("row", 5, region="north"))
    datasets.seed("already_taken", [])
    summaries = InMemoryDatasetSummaryRepository()
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = ExtractDatasetUseCase(
        dataset_repository=datasets,
        summary_repository=summaries,
        dispatcher=dispatcher,
    )

    with pytest.raises(FileExistsError):
        use_case.execute(
            ExtractDatasetInput(
                source_names=["source_a"],
                filters={"region": "north"},
                percentage=100,
                target_name="already_taken",
            )
        )

    assert summaries.get("already_taken") is None
    assert dispatcher.dispatched == []

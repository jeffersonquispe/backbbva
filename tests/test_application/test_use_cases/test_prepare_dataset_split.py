from __future__ import annotations

import pytest

from src.application.dtos.dataset_dtos import AppendDatasetRowsInput
from src.application.errors import ConflictError, ValidationError
from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)
from src.application.use_cases.datasets.append_dataset_rows import (
    AppendDatasetRowsUseCase,
)
from src.application.use_cases.datasets.prepare_dataset_split import (
    PrepareDatasetSplitUseCase,
)
from src.domain.datasets.partitioning import PARTITION_FIELD, partition_rows


class InMemoryDatasetRepository:
    def __init__(self, rows: dict[str, list[dict]]):
        self.rows = rows

    def list(self):
        return [type("Dataset", (), {"name": name})() for name in self.rows]

    def get_rows(self, name):
        return [dict(row) for row in self.rows[name]]

    def get_fields(self, name):
        return list(self.rows[name][0])

    def create(self, name, fields):
        if name in self.rows:
            raise FileExistsError(name)
        self.rows[name] = []

    def append_rows(self, name, rows):
        self.rows[name].extend(dict(row) for row in rows)
        return len(self.rows[name])

    def delete(self, name):
        self.rows.pop(name, None)


class InMemoryDatasetSummaryRepository:
    def __init__(self):
        self.rows = {}

    def get(self, name):
        return self.rows.get(name)

    def upsert(self, summary):
        self.rows[summary.dataset_name] = summary
        return summary

    def delete(self, name):
        self.rows.pop(name, None)


class RecordingDatasetAnalysisDispatcher:
    def dispatch(self, dataset_name):
        self.dataset_name = dataset_name


def test_partition_rows_are_repeatable_disjoint_and_stratified():
    rows = [
        {"id": str(index), "label": "fraud" if index % 2 else "legit"}
        for index in range(100)
    ]
    proportions = {
        "training": 0.6,
        "validation": 0.2,
        "calibration": 0.1,
        "test": 0.1,
    }
    first = partition_rows(
        rows, proportions=proportions, seed=81, stratify_fields=("label",)
    )
    second = partition_rows(
        rows, proportions=proportions, seed=81, stratify_fields=("label",)
    )

    assert first == second
    assert {name: len(part) for name, part in first.items()} == {
        "training": 60,
        "validation": 20,
        "calibration": 10,
        "test": 10,
    }
    assert {row["id"] for part in first.values() for row in part} == {
        row["id"] for row in rows
    }
    assert all(row[PARTITION_FIELD] == name for name, part in first.items() for row in part)


def test_prepare_dataset_split_persists_reproducibility_metadata():
    source = [
        {"id": str(index), "label": "fraud" if index % 2 else "legit"}
        for index in range(100)
    ]
    datasets = InMemoryDatasetRepository({"source": source})
    summaries = InMemoryDatasetSummaryRepository()
    result = PrepareDatasetSplitUseCase(datasets, summaries).execute(
        source_name="source",
        target_name="experiment-data",
        proportions={
            "training": 0.6,
            "validation": 0.2,
            "calibration": 0.1,
            "test": 0.1,
        },
        seed=42,
        stratify_fields=["label"],
    )

    summary = summaries.get("experiment-data")
    assert summary.origin == DatasetOrigin.PARTITIONED
    assert summary.split_metadata["snapshot_id"] == result["snapshot_id"]
    assert summary.split_metadata["source_content_sha256"] == result[
        "source_content_sha256"
    ]
    assert len(datasets.rows["experiment-data"]) == 100
    assert {row[PARTITION_FIELD] for row in datasets.rows["experiment-data"]} == {
        "training",
        "validation",
        "calibration",
        "test",
    }
    assert datasets.rows["source"] == source

    repeated = PrepareDatasetSplitUseCase(datasets, summaries).execute(
        source_name="source",
        target_name="experiment-data",
        proportions={
            "training": 0.6,
            "validation": 0.2,
            "calibration": 0.1,
            "test": 0.1,
        },
        seed=42,
        stratify_fields=["label"],
    )
    assert repeated == result
    assert len(datasets.rows["experiment-data"]) == 100


def test_preview_dataset_split_returns_counts_and_does_not_create_copy():
    source = [
        {"id": str(index), "channel": "web" if index % 2 else "mobile"}
        for index in range(25)
    ]
    datasets = InMemoryDatasetRepository({"source": source})
    use_case = PrepareDatasetSplitUseCase(datasets, InMemoryDatasetSummaryRepository())

    result = use_case.preview(
        source_name="source",
        proportions={
            "training": 0.6,
            "validation": 0.2,
            "calibration": 0.1,
            "test": 0.1,
        },
        seed=42,
        stratify_fields=["channel"],
    )

    assert result["source_row_count"] == 25
    assert result["partition_counts"] == {
        "training": 15,
        "validation": 6,
        "calibration": 2,
        "test": 2,
    }
    assert result["available_fields"] == ["id", "channel"]
    assert result["source_content_sha256"]
    assert list(datasets.rows) == ["source"]


def test_partitioned_dataset_rejects_appends():
    datasets = InMemoryDatasetRepository({"split": [{"id": "1"}]})
    summaries = InMemoryDatasetSummaryRepository()
    summaries.upsert(
        DatasetSummaryRecord(
            dataset_name="split",
            status=DatasetAnalysisStatus.READY,
            total_rows=1,
            origin=DatasetOrigin.PARTITIONED,
            split_metadata={"snapshot_id": "abc"},
        )
    )
    dispatcher = RecordingDatasetAnalysisDispatcher()
    use_case = AppendDatasetRowsUseCase(datasets, summaries, dispatcher)

    with pytest.raises(ConflictError, match="inmutables"):
        use_case.execute(AppendDatasetRowsInput(name="split", rows=[{"id": "2"}]))
    assert len(datasets.rows["split"]) == 1


def test_prepare_dataset_split_rejects_unknown_strata():
    datasets = InMemoryDatasetRepository({"source": [{"id": "1"}]})
    use_case = PrepareDatasetSplitUseCase(datasets, InMemoryDatasetSummaryRepository())

    with pytest.raises(ValidationError, match="no existen"):
        use_case.execute(
            source_name="source",
            target_name="split",
            proportions={
                "training": 0.6,
                "validation": 0.2,
                "calibration": 0.1,
                "test": 0.1,
            },
            seed=42,
            stratify_fields=["missing"],
        )

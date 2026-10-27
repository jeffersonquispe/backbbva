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


PROPORTIONS = {"training": 0.6, "validation": 0.2, "calibration": 0.1, "test": 0.1}


class InMemoryDatasetSnapshotRepository:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def get(self, snapshot_id):
        return next((s for s in self.snapshots if s.snapshot_id == snapshot_id), None)

    def create(self, snapshot):
        self.snapshots.append(snapshot)
        return snapshot

    def list_recent(self, limit):
        return self.snapshots[:limit]

    def delete(self, snapshot_id):
        self.snapshots = [s for s in self.snapshots if s.snapshot_id != snapshot_id]


class InMemoryAlertSchemaRepository:
    def __init__(self, active):
        self.active = active

    def get_active(self):
        return self.active


class InMemoryAlertFieldMappingRepository:
    def __init__(self, mappings):
        self.mappings = mappings

    def get(self, dataset_name):
        return self.mappings.get(dataset_name)


def _mature_snapshot():
    from datetime import UTC, date, datetime

    from src.domain.datasets.mature_sample_entities import DatasetSnapshot

    return DatasetSnapshot(
        snapshot_id="snap1",
        specification={},
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        maturing_days=4,
        strata_counts={},
        partition_counts={"training": 30, "validation": 10, "test": 10, "final": 10},
        schema_versions=(3,),
        content_hash="c" * 64,
        trigger="manual",
        dataset_refs={
            "all": "mature-sample-snap1",
            "training": "mature-sample-snap1-training",
            "validation": "mature-sample-snap1-validation",
            "test": "mature-sample-snap1-test",
            "final": "mature-sample-snap1-final",
        },
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
    )


def _schema(version, *fields):
    from src.application.ports.alert_schema_port import (
        AlertSchemaDataSource,
        AlertSchemaField,
        AlertSchemaStatus,
        AlertSchemaVersion,
    )

    return AlertSchemaVersion(
        version=version,
        status=AlertSchemaStatus.ACTIVE,
        fields=[
            AlertSchemaField(
                id=name,
                data_source=next(iter(AlertSchemaDataSource)),
                field=name,
                is_mandatory=True,
            )
            for name in fields
        ],
    )


def test_split_rejects_the_reserved_final_partition_of_a_mature_sample():
    rows = [{"id": str(index), "fraud_label": "no_fraud"} for index in range(20)]
    datasets = InMemoryDatasetRepository({"mature-sample-snap1-final": rows})
    use_case = PrepareDatasetSplitUseCase(
        datasets,
        InMemoryDatasetSummaryRepository(),
        snapshots=InMemoryDatasetSnapshotRepository([_mature_snapshot()]),
    )

    with pytest.raises(ValidationError, match="final .* reservada"):
        use_case.preview(source_name="mature-sample-snap1-final", proportions=PROPORTIONS, seed=1)
    with pytest.raises(ValidationError, match="reservada"):
        use_case.execute(
            source_name="mature-sample-snap1-final",
            target_name="leak",
            proportions=PROPORTIONS,
            seed=1,
        )
    assert "leak" not in datasets.rows


def test_split_rejects_rows_tagged_with_the_final_sampler_partition():
    rows = [
        {"id": str(index), "__aria_partition": "final" if index == 0 else "training"}
        for index in range(20)
    ]
    use_case = PrepareDatasetSplitUseCase(
        InMemoryDatasetRepository({"orphan": rows}), InMemoryDatasetSummaryRepository()
    )

    with pytest.raises(ValidationError, match="final reservada"):
        use_case.preview(source_name="orphan", proportions=PROPORTIONS, seed=1)


def test_split_of_mature_sample_records_provenance_and_drops_sampler_column():
    rows = [
        {
            "id": str(index),
            "fraud_label": "fraud" if index % 3 == 0 else "no_fraud",
            "__aria_partition": ("training", "validation", "test")[index % 3],
        }
        for index in range(30)
    ]
    datasets = InMemoryDatasetRepository({"mature-sample-snap1": rows})
    summaries = InMemoryDatasetSummaryRepository()
    use_case = PrepareDatasetSplitUseCase(
        datasets,
        summaries,
        snapshots=InMemoryDatasetSnapshotRepository([_mature_snapshot()]),
        alert_schemas=InMemoryAlertSchemaRepository(_schema(4, "id")),
    )

    result = use_case.execute(
        source_name="mature-sample-snap1",
        target_name="mature-split",
        proportions=PROPORTIONS,
        seed=7,
        stratify_fields=["fraud_label"],
    )

    assert all("__aria_partition" not in row for row in datasets.rows["mature-split"])
    assert result["source_context"] == {
        "kind": "mature_sample",
        "mature_snapshot_id": "snap1",
        "mature_content_hash": "c" * 64,
        "source_partition": "all",
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
        "maturing_days": 4,
        "excluded_partitions": ["final"],
        "sampler_partition_counts": {"test": 10, "training": 10, "validation": 10},
    }
    assert result["schema_context"]["validated_versions"] == [3]
    assert result["schema_context"]["compatible"] is False
    assert any("v3" in warning and "v4" in warning for warning in result["warnings"])
    assert summaries.get("mature-split").split_metadata["source_context"]["kind"] == (
        "mature_sample"
    )
    assert sum(
        count
        for stratum in result["strata_distribution"].values()
        for count in stratum.values()
    ) == 30


def test_split_warns_about_missing_mandatory_schema_fields_unless_mapped():
    from src.application.ports.alert_field_mapping_port import AlertFieldMapping

    rows = [{"id": str(index), "canal": "web"} for index in range(20)]
    schemas = InMemoryAlertSchemaRepository(_schema(2, "id", "channel"))
    datasets = InMemoryDatasetRepository({"source": rows})

    unmapped = PrepareDatasetSplitUseCase(
        datasets, InMemoryDatasetSummaryRepository(), alert_schemas=schemas
    ).preview(source_name="source", proportions=PROPORTIONS, seed=1)
    assert unmapped["schema_context"]["missing_mandatory_fields"] == ["channel"]
    assert unmapped["schema_context"]["context"] == "column_names"
    assert any("channel" in warning for warning in unmapped["warnings"])

    mapped = PrepareDatasetSplitUseCase(
        datasets,
        InMemoryDatasetSummaryRepository(),
        alert_schemas=schemas,
        field_mappings=InMemoryAlertFieldMappingRepository(
            {"source": AlertFieldMapping("source", 2, {"channel": "canal"})}
        ),
    ).preview(source_name="source", proportions=PROPORTIONS, seed=1)
    assert mapped["schema_context"]["compatible"] is True
    assert mapped["warnings"] == []


def test_split_rejects_sources_over_the_row_limit():
    rows = [{"id": str(index)} for index in range(20)]
    use_case = PrepareDatasetSplitUseCase(
        InMemoryDatasetRepository({"big": rows}),
        InMemoryDatasetSummaryRepository(),
        max_rows=10,
    )

    with pytest.raises(ValidationError, match="máximo para particionar es 10"):
        use_case.preview(source_name="big", proportions=PROPORTIONS, seed=1)


def test_split_with_same_seed_and_new_name_reproduces_the_assignment():
    source = [{"id": str(index), "label": str(index % 2)} for index in range(50)]
    datasets = InMemoryDatasetRepository({"source": source})
    use_case = PrepareDatasetSplitUseCase(datasets, InMemoryDatasetSummaryRepository())

    first = use_case.execute(
        source_name="source", target_name="a", proportions=PROPORTIONS, seed=9
    )
    second = use_case.execute(
        source_name="source", target_name="b", proportions=PROPORTIONS, seed=9
    )
    other_seed = use_case.execute(
        source_name="source", target_name="c", proportions=PROPORTIONS, seed=10
    )

    assignment = {
        name: {row["id"]: row[PARTITION_FIELD] for row in datasets.rows[name]}
        for name in ("a", "b", "c")
    }
    assert first["snapshot_id"] == second["snapshot_id"] != other_seed["snapshot_id"]
    assert assignment["a"] == assignment["b"]
    assert assignment["a"] != assignment["c"]

from src.domain.datasets.entities import (
    DatasetAnalysisStatus,
    DatasetOrigin,
    DatasetSummaryRecord,
)


def test_dataset_summary_defaults_are_independent() -> None:
    first = DatasetSummaryRecord(
        dataset_name="first",
        status=DatasetAnalysisStatus.PENDING,
        total_rows=0,
    )
    second = DatasetSummaryRecord(
        dataset_name="second",
        status=DatasetAnalysisStatus.READY,
        total_rows=3,
    )

    first.available_fields.append("event_id")
    first.field_distributions["channel"] = {"web": 3}
    first.source_dataset_names.append("source")

    assert second.available_fields == []
    assert second.field_distributions == {}
    assert second.source_dataset_names == []


def test_dataset_origin_tracks_initial_creation_source() -> None:
    summary = DatasetSummaryRecord(
        dataset_name="curated",
        status=DatasetAnalysisStatus.READY,
        total_rows=1,
        origin=DatasetOrigin.ALERT_CURATED,
    )

    assert summary.origin is DatasetOrigin.ALERT_CURATED

from __future__ import annotations

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSummaryRecord,
)
from src.application.ports.dataset_port import DatasetRecord
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.use_cases.datasets.get_dataset_summary import (
    GetDatasetSummaryUseCase,
)


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self, records: dict[str, DatasetSummaryRecord]) -> None:
        self._records = records

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._records[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._records.get(dataset_name)


class InMemoryDatasetRepository:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list(self) -> list[DatasetRecord]:
        return [DatasetRecord(name="ds", row_count=len(self._rows))]

    def get_rows(self, name: str) -> list[dict]:
        return self._rows

    def delete(self, name: str) -> None:
        pass


def test_get_dataset_summary_computes_percentages_from_counts() -> None:
    summary_repo = InMemoryDatasetSummaryRepository(
        {
            "ds": DatasetSummaryRecord(
                dataset_name="ds",
                status=DatasetAnalysisStatus.READY,
                total_rows=4,
                field_distributions={
                    "marcacion_final": {"no-risk": 3, "risk": 1},
                },
            )
        }
    )
    use_case = GetDatasetSummaryUseCase(summary_repo)

    output = use_case.execute("ds")

    assert output is not None
    values = output.field_distributions["marcacion_final"]
    assert values[0].value == "no-risk"
    assert values[0].count == 3
    assert values[0].percentage == 75.0
    assert values[1].value == "risk"
    assert values[1].percentage == 25.0
    # Backward-compatible fallback for summaries persisted before the full
    # catalog existed.
    assert output.available_fields == ["marcacion_final"]


def test_get_dataset_summary_derives_full_catalog_for_legacy_summary() -> None:
    summary_repo = InMemoryDatasetSummaryRepository(
        {
            "ds": DatasetSummaryRecord(
                dataset_name="ds",
                status=DatasetAnalysisStatus.READY,
                total_rows=1,
                field_distributions={"marcacion_final": {"risk": 1}},
            )
        }
    )
    dataset_repo = InMemoryDatasetRepository(
        [
            {
                "marcacion_final": "risk",
                "amount_value": "122000",
                "biocatch": {"isOnCall": "False"},
            }
        ]
    )

    output = GetDatasetSummaryUseCase(summary_repo, dataset_repo).execute("ds")

    assert output.available_fields == [
        "marcacion_final",
        "amount_value",
        "biocatch.isOnCall",
    ]


def test_get_dataset_summary_returns_none_when_missing() -> None:
    use_case = GetDatasetSummaryUseCase(InMemoryDatasetSummaryRepository({}))

    assert use_case.execute("missing") is None


def test_get_dataset_summary_handles_zero_total_rows_without_dividing_by_zero() -> None:
    summary_repo = InMemoryDatasetSummaryRepository(
        {
            "ds": DatasetSummaryRecord(
                dataset_name="ds",
                status=DatasetAnalysisStatus.PENDING,
                total_rows=0,
                field_distributions={},
            )
        }
    )
    use_case = GetDatasetSummaryUseCase(summary_repo)

    output = use_case.execute("ds")

    assert output.field_distributions == {}

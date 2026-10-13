from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.ports.dataset_analysis_port import (
    DatasetAnalysisStatus,
    DatasetSampleRecord,
    DatasetSampleRepository,
    DatasetSummaryRecord,
    DatasetSummaryRepository,
)
from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.application.use_cases.datasets.analyze_dataset import AnalyzeDatasetUseCase


class InMemoryDatasetRepository(DatasetRepository):
    def __init__(self, rows_by_name: dict[str, list[dict]]) -> None:
        self._rows_by_name = rows_by_name

    def list(self) -> list[DatasetRecord]:
        return [DatasetRecord(name=n, row_count=len(r)) for n, r in self._rows_by_name.items()]

    def get_rows(self, name: str) -> list[dict]:
        return self._rows_by_name[name]


class InMemoryDatasetSampleRepository(DatasetSampleRepository):
    def __init__(self) -> None:
        self.by_dataset: dict[str, list[DatasetSampleRecord]] = {}

    def create_batch(self, samples: list[DatasetSampleRecord]) -> None:
        for sample in samples:
            self.by_dataset.setdefault(sample.dataset_name, []).append(sample)

    def list_by_dataset(self, dataset_name: str) -> list[DatasetSampleRecord]:
        return self.by_dataset.get(dataset_name, [])

    def delete_by_dataset(self, dataset_name: str) -> None:
        self.by_dataset.pop(dataset_name, None)


class InMemoryDatasetSummaryRepository(DatasetSummaryRepository):
    def __init__(self) -> None:
        self._by_name: dict[str, DatasetSummaryRecord] = {}

    def upsert(self, summary: DatasetSummaryRecord) -> DatasetSummaryRecord:
        self._by_name[summary.dataset_name] = summary
        return summary

    def get(self, dataset_name: str) -> DatasetSummaryRecord | None:
        return self._by_name.get(dataset_name)


def test_analyze_dataset_persists_samples_and_ready_summary() -> None:
    rows = [
        {"marcacion_final": "no-risk", "tipo": "NoFraude", "razon_marcacion": "[NF___ANLISIS]",
         "integrationpoint": "00 - Compra", "triggered_rules": "[CUSTOMER - Score1000Net]"},
        {"marcacion_final": "risk", "tipo": "Fraude", "razon_marcacion": "[FR___ESTAFA, RECLAMO]",
         "integrationpoint": "00 - Compra",
         "triggered_rules": "[CUSTOMER - Score1000Net, CUSTOMER - dg_rat_score600]"},
    ]
    datasets = InMemoryDatasetRepository({"ds": rows})
    samples = InMemoryDatasetSampleRepository()
    summaries = InMemoryDatasetSummaryRepository()
    summaries.upsert(
        DatasetSummaryRecord(
            dataset_name="ds",
            status=DatasetAnalysisStatus.PENDING,
            total_rows=0,
            field_distributions={},
            uploaded_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    use_case = AnalyzeDatasetUseCase(datasets, samples, summaries)

    use_case.execute("ds")

    stored = samples.list_by_dataset("ds")
    assert len(stored) == 2
    assert stored[0].marcacion_final == "no-risk"
    assert stored[0].integration_point == "00 - Compra"
    assert stored[0].sample_id == "00000000"
    # Raw bracketed string is kept as-is on the per-sample record - only the
    # aggregate distribution splits it into members.
    assert stored[1].razon_marcacion == "[FR___ESTAFA, RECLAMO]"
    assert stored[1].triggered_rules == "[CUSTOMER - Score1000Net, CUSTOMER - dg_rat_score600]"

    summary = summaries.get("ds")
    assert summary.status == DatasetAnalysisStatus.READY
    assert summary.total_rows == 2
    assert summary.available_fields == [
        "marcacion_final",
        "tipo",
        "razon_marcacion",
        "integrationpoint",
        "triggered_rules",
    ]
    assert summary.field_distributions["marcacion_final"] == {"no-risk": 1, "risk": 1}
    assert summary.field_distributions["tipo"] == {"NoFraude": 1, "Fraude": 1}
    assert summary.field_distributions["razon_marcacion"] == {
        "NF___ANLISIS": 1,
        "FR___ESTAFA": 1,
        "RECLAMO": 1,
    }
    assert summary.field_distributions["triggered_rules"] == {
        "CUSTOMER - Score1000Net": 2,
        "CUSTOMER - dg_rat_score600": 1,
    }
    # uploaded_at must survive re-analysis, only updated_at moves.
    assert summary.uploaded_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_analyze_dataset_profiles_non_aria_columns_on_extracted_style_dataset() -> None:
    # An extracted/empty-style dataset with none of the 5 ARIA columns -
    # before the fix, compute_distributions was hardcoded to the 5 ARIA
    # fields (via extract_fields always extracting exactly those 5 keys),
    # so a dataset shaped like this would only ever produce "unknown"-only
    # distributions and never profile its actual "foo" column.
    rows = [{"foo": "a"}, {"foo": "a"}, {"foo": "b"}]
    datasets = InMemoryDatasetRepository({"ds": rows})
    samples = InMemoryDatasetSampleRepository()
    summaries = InMemoryDatasetSummaryRepository()
    use_case = AnalyzeDatasetUseCase(datasets, samples, summaries)

    use_case.execute("ds")

    summary = summaries.get("ds")
    assert summary.status == DatasetAnalysisStatus.READY
    assert summary.available_fields == ["foo"]
    # The 5 ARIA fields are still first-class in the distributions (for
    # backward-compatible UI labeling) even though they're absent from this
    # dataset's actual columns - every row falls into "unknown" for them.
    assert summary.field_distributions["tipo"] == {"unknown": 3}
    assert summary.field_distributions["marcacion_final"] == {"unknown": 3}
    # The dataset's real column is now profiled too, instead of being
    # silently dropped or raising KeyError.
    assert summary.field_distributions["foo"] == {"a": 2, "b": 1}


def test_analyze_dataset_marks_failed_and_reraises_on_error() -> None:
    datasets = InMemoryDatasetRepository({})  # "ds" missing -> get_rows raises KeyError
    samples = InMemoryDatasetSampleRepository()
    summaries = InMemoryDatasetSummaryRepository()
    use_case = AnalyzeDatasetUseCase(datasets, samples, summaries)

    with pytest.raises(KeyError):
        use_case.execute("ds")

    summary = summaries.get("ds")
    assert summary.status == DatasetAnalysisStatus.FAILED
    assert summary.error is not None

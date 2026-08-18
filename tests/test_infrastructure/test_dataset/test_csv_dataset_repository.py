from __future__ import annotations

from pathlib import Path

from src.infrastructure.persistence.dataset.filesystem.csv_dataset_repository import (
    FilesystemCsvDatasetRepository,
)


def test_list_counts_rows_and_get_rows_unflattens_dotted_headers(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "eventId,customerId,object.triggeredRules,amount.baseValue\n"
        "e-1,c-1,RULE_A,100\n"
        "e-2,c-2,RULE_B,250\n"
    )
    repo = FilesystemCsvDatasetRepository(tmp_path)

    datasets = repo.list()
    assert len(datasets) == 1
    assert datasets[0].name == "sample"
    assert datasets[0].row_count == 2

    rows = repo.get_rows("sample")
    assert rows == [
        {
            "eventId": "e-1",
            "customerId": "c-1",
            "object": {"triggeredRules": "RULE_A"},
            "amount": {"baseValue": "100"},
        },
        {
            "eventId": "e-2",
            "customerId": "c-2",
            "object": {"triggeredRules": "RULE_B"},
            "amount": {"baseValue": "250"},
        },
    ]


def test_list_returns_empty_when_directory_missing(tmp_path: Path) -> None:
    repo = FilesystemCsvDatasetRepository(tmp_path / "does-not-exist")
    assert repo.list() == []


def test_get_rows_drops_leading_unnamed_index_column(tmp_path: Path) -> None:
    # Real-world artifact: pandas' to_csv(index=True) leaves the first
    # header empty. DynamoDB rejects an empty attribute name outright, so
    # this must never survive into a row dict.
    csv_path = tmp_path / "indexed.csv"
    csv_path.write_text(",eventId,customerId\n0,e-1,c-1\n")
    repo = FilesystemCsvDatasetRepository(tmp_path)

    rows = repo.get_rows("indexed")

    assert rows == [{"eventId": "e-1", "customerId": "c-1"}]


def test_list_and_get_rows_handle_fields_past_python_default_csv_limit(
    tmp_path: Path,
) -> None:
    # Regression: real transacciones_json blobs run 280KB+, well past
    # Python's default 131072-byte csv field limit - list() used to raise
    # _csv.Error before FilesystemCsvDatasetRepository raised it globally.
    huge_field = "x" * 200_000
    csv_path = tmp_path / "big.csv"
    csv_path.write_text(f"eventId,payload\ne-1,{huge_field}\n")
    repo = FilesystemCsvDatasetRepository(tmp_path)

    datasets = repo.list()
    assert datasets[0].row_count == 1

    rows = repo.get_rows("big")
    assert rows[0]["payload"] == huge_field

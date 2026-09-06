from __future__ import annotations

import pytest

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
    assert repo.get_fields("sample") == [
        "eventId",
        "customerId",
        "object.triggeredRules",
        "amount.baseValue",
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
    assert repo.get_fields("indexed") == ["eventId", "customerId"]


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


def test_create_writes_header_only_csv(tmp_path: Path) -> None:
    repo = FilesystemCsvDatasetRepository(tmp_path)

    repo.create("new_dataset", ["eventId", "customerId", "object.triggeredRules"])

    csv_path = tmp_path / "new_dataset.csv"
    # Path.read_text() applies universal-newline translation, so the CSV
    # writer's \r\n line terminator reads back as plain \n here.
    assert csv_path.read_text() == "eventId,customerId,object.triggeredRules\n"
    assert repo.get_fields("new_dataset") == [
        "eventId",
        "customerId",
        "object.triggeredRules",
    ]
    assert repo.get_rows("new_dataset") == []


def test_create_raises_when_dataset_already_exists(tmp_path: Path) -> None:
    repo = FilesystemCsvDatasetRepository(tmp_path)
    repo.create("dupe", ["eventId"])

    with pytest.raises(FileExistsError):
        repo.create("dupe", ["eventId"])


def test_append_rows_flattens_nested_values_and_round_trips_on_get_rows(
    tmp_path: Path,
) -> None:
    repo = FilesystemCsvDatasetRepository(tmp_path)
    repo.create("events", ["eventId", "customerId", "object.triggeredRules"])

    new_total = repo.append_rows(
        "events",
        [
            {
                "eventId": "e-1",
                "customerId": "c-1",
                "object": {"triggeredRules": "RULE_A"},
            },
            {
                "eventId": "e-2",
                "customerId": "c-2",
                "object": {"triggeredRules": "RULE_B"},
            },
        ],
    )

    assert new_total == 2
    assert repo.get_rows("events") == [
        {
            "eventId": "e-1",
            "customerId": "c-1",
            "object": {"triggeredRules": "RULE_A"},
        },
        {
            "eventId": "e-2",
            "customerId": "c-2",
            "object": {"triggeredRules": "RULE_B"},
        },
    ]


def test_append_rows_drops_fields_not_in_existing_header(tmp_path: Path) -> None:
    repo = FilesystemCsvDatasetRepository(tmp_path)
    repo.create("events", ["eventId"])

    new_total = repo.append_rows(
        "events",
        [{"eventId": "e-1", "extra": {"nested": "dropped"}}],
    )

    assert new_total == 1
    assert repo.get_rows("events") == [{"eventId": "e-1"}]


def test_append_rows_appends_to_existing_data(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("eventId,customerId\ne-1,c-1\n")
    repo = FilesystemCsvDatasetRepository(tmp_path)

    new_total = repo.append_rows("sample", [{"eventId": "e-2", "customerId": "c-2"}])

    assert new_total == 2
    assert repo.get_rows("sample") == [
        {"eventId": "e-1", "customerId": "c-1"},
        {"eventId": "e-2", "customerId": "c-2"},
    ]


def test_append_rows_raises_when_dataset_missing(tmp_path: Path) -> None:
    repo = FilesystemCsvDatasetRepository(tmp_path)

    with pytest.raises(FileNotFoundError):
        repo.append_rows("missing", [{"eventId": "e-1"}])


def test_append_rows_preserves_column_alignment_with_leading_unnamed_column(
    tmp_path: Path,
) -> None:
    # Regression: a pandas to_csv(index=True) export (real datasets have
    # this exact shape) has a blank/unnamed first column. append_rows must
    # not reuse get_fields()'s display-oriented filtering (which drops that
    # blank name) to build its CSV writer header - doing so silently drops
    # a real column position and shifts every appended value one column
    # left of where the file's actual header puts it. Found by testing
    # against a real, larger reference dataset with this shape.
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(",name,amount\n0,alice,100\n1,bob,200\n")
    repo = FilesystemCsvDatasetRepository(tmp_path)

    repo.append_rows("sample", [{"name": "carol", "amount": "300"}])

    assert repo.get_rows("sample") == [
        {"name": "alice", "amount": "100"},
        {"name": "bob", "amount": "200"},
        {"name": "carol", "amount": "300"},
    ]


def test_get_rows_page_returns_slice_and_total(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "eventId\n" + "".join(f"e-{i}\n" for i in range(5))
    )
    repo = FilesystemCsvDatasetRepository(tmp_path)

    page, total = repo.get_rows_page("sample", offset=1, limit=2)

    assert total == 5
    assert page == [{"eventId": "e-1"}, {"eventId": "e-2"}]


def test_get_rows_page_out_of_range_offset_returns_empty_page(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("eventId\ne-0\ne-1\n")
    repo = FilesystemCsvDatasetRepository(tmp_path)

    page, total = repo.get_rows_page("sample", offset=10, limit=5)

    assert page == []
    assert total == 2

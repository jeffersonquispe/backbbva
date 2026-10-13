from __future__ import annotations

import io
import pytest

from src.application.ports.object_storage_port import ObjectStoragePort, ObjectStorageRef
from src.infrastructure.persistence.dataset.minio.csv_dataset_repository import (
    MinioCsvDatasetRepository,
)


class InMemoryObjectStoragePort(ObjectStoragePort):
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put_text(
        self,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> ObjectStorageRef:
        return self.put_bytes(key, content.encode("utf-8"), content_type)

    def put_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectStorageRef:
        self._objects[key] = content
        return ObjectStorageRef(bucket="test-bucket", key=key, uri=f"s3://test-bucket/{key}")

    def get_bytes(self, key: str) -> bytes:
        return self._objects[key]

    def get_stream(self, key: str):
        return io.BytesIO(self._objects[key])

    def list_keys(self, suffix: str = "") -> list[str]:
        return [key for key in self._objects if key.endswith(suffix)]

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


def test_list_and_get_rows_round_trip() -> None:
    storage = InMemoryObjectStoragePort()
    storage.put_text(
        "customers.csv",
        "name,amount.baseValue\nalice,10\nbob,20\n",
        content_type="text/csv",
    )
    repo = MinioCsvDatasetRepository(object_storage=storage)

    records = repo.list()
    assert len(records) == 1
    assert records[0].name == "customers"
    # Listing object storage must not download each CSV just to count rows.
    # The API enriches this value from the persisted dataset summary.
    assert records[0].row_count == 0

    rows = repo.get_rows("customers")
    assert rows == [
        {"name": "alice", "amount": {"baseValue": "10"}},
        {"name": "bob", "amount": {"baseValue": "20"}},
    ]


def test_create_writes_header_only_object() -> None:
    storage = InMemoryObjectStoragePort()
    repo = MinioCsvDatasetRepository(object_storage=storage)

    repo.create("new_dataset", ["name", "amount"])

    assert "new_dataset.csv" in storage.list_keys(".csv")
    assert repo.get_fields("new_dataset") == ["name", "amount"]
    assert repo.get_rows("new_dataset") == []


def test_create_raises_when_dataset_already_exists() -> None:
    storage = InMemoryObjectStoragePort()
    repo = MinioCsvDatasetRepository(object_storage=storage)
    repo.create("dup", ["name"])

    with pytest.raises(FileExistsError):
        repo.create("dup", ["name"])


def test_append_rows_flattens_nested_values_and_returns_new_total() -> None:
    storage = InMemoryObjectStoragePort()
    repo = MinioCsvDatasetRepository(object_storage=storage)
    repo.create("events", ["name", "amount.baseValue"])

    new_total = repo.append_rows(
        "events",
        [
            {"name": "alice", "amount": {"baseValue": 10}},
            {"name": "bob", "amount": {"baseValue": 20}},
        ],
    )

    assert new_total == 2
    rows = repo.get_rows("events")
    assert rows == [
        {"name": "alice", "amount": {"baseValue": "10"}},
        {"name": "bob", "amount": {"baseValue": "20"}},
    ]

    # A second append should accumulate on top of the existing rows.
    new_total = repo.append_rows("events", [{"name": "carol", "amount": {"baseValue": 30}}])
    assert new_total == 3
    assert len(repo.get_rows("events")) == 3


def test_append_rows_preserves_column_alignment_with_leading_unnamed_column() -> None:
    # Regression: a pandas to_csv(index=True) export (real datasets have
    # this exact shape) has a blank/unnamed first column. append_rows must
    # not reuse get_fields()'s display-oriented filtering (which drops that
    # blank name) to build its CSV writer header - doing so silently drops
    # a real column position and shifts every value one column left,
    # including for already-existing rows since this adapter rewrites the
    # whole object on every append. Found by testing against a real, larger
    # reference dataset with this shape.
    storage = InMemoryObjectStoragePort()
    storage.put_text("sample.csv", ",name,amount\n0,alice,100\n1,bob,200\n", content_type="text/csv")
    repo = MinioCsvDatasetRepository(object_storage=storage)

    repo.append_rows("sample", [{"name": "carol", "amount": "300"}])

    assert repo.get_rows("sample") == [
        {"name": "alice", "amount": "100"},
        {"name": "bob", "amount": "200"},
        {"name": "carol", "amount": "300"},
    ]


def test_get_rows_page_slices_and_reports_total() -> None:
    storage = InMemoryObjectStoragePort()
    repo = MinioCsvDatasetRepository(object_storage=storage)
    repo.create("paged", ["name"])
    repo.append_rows("paged", [{"name": f"row{i}"} for i in range(5)])

    page, total = repo.get_rows_page("paged", offset=1, limit=2)
    # The repository deliberately avoids scanning the remaining object just
    # to count rows; the API obtains the exact total from dataset summaries.
    assert total == 0
    assert page == [{"name": "row1"}, {"name": "row2"}]

    page, total = repo.get_rows_page("paged", offset=10, limit=2)
    assert total == 0
    assert page == []

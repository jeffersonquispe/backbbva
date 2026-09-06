from __future__ import annotations

import csv
import io
from typing import Any

from botocore.exceptions import ClientError

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.persistence.dataset.csv_utils import flatten_row, unflatten_row


class MinioCsvDatasetRepository(DatasetRepository):
    def __init__(self, object_storage: ObjectStoragePort) -> None:
        self._object_storage = object_storage

    def list(self) -> list[DatasetRecord]:
        records = []
        for key in self._object_storage.list_keys(".csv"):
            name = key[: -len(".csv")]
            row_count = sum(1 for _ in csv.reader(self._lines(key))) - 1
            records.append(DatasetRecord(name=name, row_count=max(row_count, 0)))
        return records

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return [unflatten_row(row) for row in csv.DictReader(self._lines(f"{name}.csv"))]

    def get_fields(self, name: str) -> list[str]:
        reader = csv.DictReader(self._lines(f"{name}.csv"))
        return [field for field in (reader.fieldnames or []) if field]

    def get_rows_page(self, name: str, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        rows = self.get_rows(name)
        return rows[offset : offset + limit], len(rows)

    def create(self, name: str, fields: list[str]) -> None:
        if f"{name}.csv" in self._object_storage.list_keys(".csv"):
            raise FileExistsError(f"Dataset '{name}' already exists")
        buffer = io.StringIO()
        csv.writer(buffer).writerow(fields)
        self._object_storage.put_text(f"{name}.csv", buffer.getvalue(), content_type="text/csv")

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        if f"{name}.csv" in self._object_storage.list_keys(".csv"):
            raise FileExistsError(f"Dataset '{name}' already exists")
        self._object_storage.put_bytes(f"{name}.csv", content, content_type="text/csv")

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        key = f"{name}.csv"
        reader = csv.DictReader(self._lines(key))
        fields = [field for field in (reader.fieldnames or []) if field]
        all_rows = list(reader) + [flatten_row(row) for row in rows]

        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({field: row.get(field, "") for field in fields})

        self._object_storage.put_text(key, buffer.getvalue(), content_type="text/csv")
        return len(all_rows)

    def delete(self, name: str) -> None:
        self._object_storage.delete(f"{name}.csv")

    def _lines(self, key: str) -> io.StringIO:
        # Normalizes a missing-object lookup to FileNotFoundError - the
        # exception type every dataset router route already catches for a
        # 404 - instead of leaking a raw botocore ClientError (S3 NoSuchKey)
        # or a plain KeyError (from in-memory test fakes) as an unhandled 500.
        try:
            content = self._object_storage.get_bytes(key)
        except (ClientError, KeyError) as exc:
            raise FileNotFoundError(key) from exc
        return io.StringIO(content.decode("utf-8"))

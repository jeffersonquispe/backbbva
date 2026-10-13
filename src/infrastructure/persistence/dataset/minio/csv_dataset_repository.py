from __future__ import annotations

import csv
import io
from typing import Any, BinaryIO

from botocore.exceptions import ClientError

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.persistence.dataset.csv_utils import flatten_row, unflatten_row


class MinioCsvDatasetRepository(DatasetRepository):
    def __init__(self, object_storage: ObjectStoragePort) -> None:
        self._object_storage = object_storage

    def list(self) -> list[DatasetRecord]:
        # Listing must not download every object. A single uploaded dataset
        # can be gigabytes large; decoding it merely to count rows can kill
        # the API process before it can send the library response. Exact row
        # totals are persisted by the asynchronous analysis summary instead.
        return [
            DatasetRecord(name=key[: -len(".csv")], row_count=0)
            for key in self._object_storage.list_keys(".csv")
        ]

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        return [
            unflatten_row(row) for row in csv.DictReader(self._lines(f"{name}.csv"))
        ]

    def iter_rows(self, name: str):
        """Yield rows directly from MinIO without materializing the CSV."""
        try:
            stream = self._object_storage.get_stream(f"{name}.csv")
        except (ClientError, KeyError) as exc:
            raise FileNotFoundError(name) from exc
        with io.TextIOWrapper(stream, encoding="utf-8", newline="") as text:
            for row in csv.DictReader(text):
                yield unflatten_row(row)

    def get_fields(self, name: str) -> list[str]:
        try:
            stream = self._object_storage.get_stream(f"{name}.csv")
        except (ClientError, KeyError) as exc:
            raise FileNotFoundError(name) from exc
        with io.TextIOWrapper(stream, encoding="utf-8", newline="") as text:
            reader = csv.DictReader(text)
            return [field for field in (reader.fieldnames or []) if field]

    def get_size(self, name: str) -> int:
        return self._object_storage.get_size(f"{name}.csv")

    def get_rows_page(
        self, name: str, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        # Preview paths must not materialize or scan a multi-GB CSV merely to
        # show 25 rows. The API enriches the total from the persisted summary.
        page: list[dict[str, Any]] = []
        for index, row in enumerate(self.iter_rows(name)):
            if index < offset:
                continue
            if len(page) >= limit:
                break
            page.append(row)
        return page, 0

    def create(self, name: str, fields: list[str]) -> None:
        if self._name_exists(name):
            raise FileExistsError(f"Dataset '{name}' already exists")
        buffer = io.StringIO()
        csv.writer(buffer).writerow(fields)
        self._object_storage.put_text(
            f"{name}.csv", buffer.getvalue(), content_type="text/csv"
        )

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        if self._name_exists(name):
            raise FileExistsError(f"Dataset '{name}' already exists")
        self._object_storage.put_bytes(f"{name}.csv", content, content_type="text/csv")

    def create_from_csv_file(self, name: str, file: BinaryIO) -> None:
        if self._name_exists(name):
            raise FileExistsError(f"Dataset '{name}' already exists")
        self._object_storage.put_file(f"{name}.csv", file, content_type="text/csv")

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        key = f"{name}.csv"
        reader = csv.DictReader(self._lines(key))
        # Deliberately NOT the get_fields()-style filter here - it drops a
        # blank/unnamed column (e.g. pandas to_csv(index=True)'s leading
        # index column, confirmed present in real exports). Since this whole
        # file gets rewritten on every append, filtering it out here would
        # shift every column one position left - including for the
        # already-existing rows re-encoded below, not just the new ones.
        fields = reader.fieldnames or []
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

    def _name_exists(self, name: str) -> bool:
        return any(
            key[: -len(".csv")].casefold() == name.casefold()
            for key in self._object_storage.list_keys(".csv")
        )

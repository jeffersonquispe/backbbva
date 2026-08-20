from __future__ import annotations

import csv
import io
from typing import Any

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.persistence.dataset.csv_utils import unflatten_row


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

    def delete(self, name: str) -> None:
        self._object_storage.delete(f"{name}.csv")

    def _lines(self, key: str) -> io.StringIO:
        content = self._object_storage.get_bytes(key)
        return io.StringIO(content.decode("utf-8"))

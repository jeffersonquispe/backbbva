from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.infrastructure.persistence.dataset.csv_utils import unflatten_row


class FilesystemCsvDatasetRepository(DatasetRepository):
    def __init__(self, datasets_dir: Path) -> None:
        self._dir = datasets_dir

    def list(self) -> list[DatasetRecord]:
        if not self._dir.is_dir():
            return []
        records = []
        for path in sorted(self._dir.glob("*.csv")):
            with path.open(newline="", encoding="utf-8") as f:
                row_count = sum(1 for _ in csv.reader(f)) - 1  # minus header
            records.append(DatasetRecord(name=path.stem, row_count=max(row_count, 0)))
        return records

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        path = self._dir / f"{name}.csv"
        with path.open(newline="", encoding="utf-8") as f:
            return [unflatten_row(row) for row in csv.DictReader(f)]

    def delete(self, name: str) -> None:
        (self._dir / f"{name}.csv").unlink(missing_ok=True)

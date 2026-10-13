from __future__ import annotations

import csv
import shutil
from pathlib import Path
from typing import Any, BinaryIO

from src.application.ports.dataset_port import DatasetRecord, DatasetRepository
from src.infrastructure.persistence.dataset.csv_utils import flatten_row, unflatten_row


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

    def get_fields(self, name: str) -> list[str]:
        path = self._dir / f"{name}.csv"
        with path.open(newline="", encoding="utf-8") as f:
            return [field for field in (csv.DictReader(f).fieldnames or []) if field]

    def get_size(self, name: str) -> int:
        return (self._dir / f"{name}.csv").stat().st_size

    def get_rows_page(
        self, name: str, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.get_rows(name)
        return rows[offset : offset + limit], len(rows)

    def create(self, name: str, fields: list[str]) -> None:
        path = self._dir / f"{name}.csv"
        if self._name_exists(name):
            raise FileExistsError(f"Dataset '{name}' already exists")
        self._dir.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        path = self._dir / f"{name}.csv"
        if self._name_exists(name):
            raise FileExistsError(f"Dataset '{name}' already exists")
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def create_from_csv_file(self, name: str, file: BinaryIO) -> None:
        path = self._dir / f"{name}.csv"
        if self._name_exists(name):
            raise FileExistsError(f"Dataset '{name}' already exists")
        self._dir.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as destination:
            shutil.copyfileobj(file, destination, length=1024 * 1024)

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        path = self._dir / f"{name}.csv"
        # Deliberately NOT get_fields() here - it filters out a blank/unnamed
        # column (e.g. pandas to_csv(index=True)'s leading index column,
        # confirmed present in real exports) for clean display purposes.
        # Reusing that filtered list as the CSV writer's fieldnames would
        # silently drop a real column position, shifting every written value
        # one column left of where the file's actual header puts it.
        with path.open(newline="", encoding="utf-8") as f:
            fields = csv.DictReader(f).fieldnames or []
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            for row in rows:
                writer.writerow(flatten_row(row))
        with path.open(newline="", encoding="utf-8") as f:
            total = sum(1 for _ in csv.reader(f)) - 1  # minus header
        return max(total, 0)

    def delete(self, name: str) -> None:
        (self._dir / f"{name}.csv").unlink(missing_ok=True)

    def _name_exists(self, name: str) -> bool:
        return any(
            path.stem.casefold() == name.casefold() for path in self._dir.glob("*.csv")
        )

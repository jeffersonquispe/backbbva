from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol


@dataclass
class DatasetRecord:
    name: str
    row_count: int


class DatasetRepository(Protocol):
    def list(self) -> list[DatasetRecord]:
        ...

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        ...

    def get_fields(self, name: str) -> list[str]:
        """Return dataset columns without loading all rows when possible."""
        ...

    def get_size(self, name: str) -> int:
        """Return the stored CSV size without loading its contents."""
        ...

    def get_rows_page(self, name: str, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Return one page of rows plus the dataset's total row count."""
        ...

    def create(self, name: str, fields: list[str]) -> None:
        """Create a new dataset containing only a header row (no data rows)."""
        ...

    def create_from_csv_bytes(self, name: str, content: bytes) -> None:
        """Create a new dataset by writing a raw CSV file verbatim (e.g. a
        browser upload) - no parsing/validation, unlike create()+append_rows()
        which take already-shaped rows. Raises FileExistsError if the name
        is taken, same as create()."""
        ...

    def create_from_csv_file(self, name: str, file: BinaryIO) -> None:
        """Create a dataset by streaming an already-spooled CSV file."""
        ...

    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int:
        """Append rows to an existing dataset. Returns the new total row count."""
        ...

    def delete(self, name: str) -> None:
        ...

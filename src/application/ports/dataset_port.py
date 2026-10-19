from __future__ import annotations

import builtins
from typing import Any, BinaryIO, Protocol

from src.domain.datasets.entities import DatasetRecord


class DatasetRepository(Protocol):
    def list(self) -> list[DatasetRecord]: ...

    def get_rows(self, name: str) -> builtins.list[dict[str, Any]]: ...

    def get_fields(self, name: str) -> builtins.list[str]:
        """Return dataset columns without loading all rows when possible."""
        ...

    def get_size(self, name: str) -> int:
        """Return the stored CSV size without loading its contents."""
        ...

    def get_rows_page(
        self, name: str, offset: int, limit: int
    ) -> tuple[builtins.list[dict[str, Any]], int]:
        """Return one page of rows plus the dataset's total row count."""
        ...

    def create(self, name: str, fields: builtins.list[str]) -> None:
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

    def append_rows(self, name: str, rows: builtins.list[dict[str, Any]]) -> int:
        """Append rows to an existing dataset. Returns the new total row count."""
        ...

    def delete(self, name: str) -> None: ...

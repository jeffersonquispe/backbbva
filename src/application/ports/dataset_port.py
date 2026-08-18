from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class DatasetRecord:
    name: str
    row_count: int


class DatasetRepository(Protocol):
    def list(self) -> list[DatasetRecord]:
        ...

    def get_rows(self, name: str) -> list[dict[str, Any]]:
        ...

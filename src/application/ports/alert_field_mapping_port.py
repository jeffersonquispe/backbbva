from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class AlertFieldMapping:
    """A historical export mapping for one dataset and schema version."""

    dataset_name: str
    schema_version: int
    # Canonical alert field -> external dataset column name.
    mappings: dict[str, str] = field(default_factory=dict)
    updated_at: datetime | None = None


class AlertFieldMappingRepository(Protocol):
    def get(self, dataset_name: str) -> AlertFieldMapping | None:
        ...

    def save(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        ...

    def delete(self, dataset_name: str) -> None:
        ...

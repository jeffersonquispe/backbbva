from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class AlertFieldMapping:
    """How an alert's raw payload fields translate into a specific
    dataset's columns when curating an alert into it - e.g. alert.payload's
    "eventId" -> the dataset's "eventid" column. One mapping per dataset,
    since different datasets can have entirely different column shapes
    (an ARIA-shaped reference dataset vs. a raw-payload-shaped one).
    Mapped fields are applied on top of the existing pass-through/intersect
    behavior (CurateAlertToDatasetUseCase), not instead of it - a field with
    no explicit mapping still passes through under its own flattened name if
    the target dataset happens to have a matching column."""

    dataset_name: str
    # alert.payload dotted field path -> dataset column name.
    mappings: dict[str, str] = field(default_factory=dict)
    updated_at: datetime | None = None


class AlertFieldMappingRepository(Protocol):
    def get(self, dataset_name: str) -> AlertFieldMapping | None:
        ...

    def upsert(self, mapping: AlertFieldMapping) -> AlertFieldMapping:
        ...

    def delete(self, dataset_name: str) -> None:
        ...

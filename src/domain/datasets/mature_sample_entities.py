from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class DatasetSnapshot:
    snapshot_id: str
    specification: dict[str, object]
    period_start: date
    period_end: date
    maturing_days: int
    strata_counts: dict[str, int]
    partition_counts: dict[str, int]
    schema_versions: tuple[int, ...]
    content_hash: str
    trigger: str
    dataset_refs: dict[str, str]
    created_at: datetime


@dataclass(frozen=True)
class DatasetSamplerState:
    state_id: str
    last_snapshot_id: str | None = None
    last_completed_at: datetime | None = None
    last_period_key: str | None = None
    matured_alert_count: int = 0
    latest_strata_counts: dict[str, int] | None = None


@dataclass(frozen=True)
class MatureSamplerSchemaMapping:
    initial_mark_field: str = ""
    initial_marking_date_field: str = ""
    target_field: str = ""
    marking_date_field: str = ""
    label_value_mapping: dict[str, str] | None = None

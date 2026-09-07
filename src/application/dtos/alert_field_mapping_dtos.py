from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class GetAlertFieldMappingOutput:
    dataset_name: str
    mappings: dict[str, str] = field(default_factory=dict)
    updated_at: datetime | None = None


@dataclass
class SaveAlertFieldMappingInput:
    dataset_name: str
    mappings: dict[str, str]


@dataclass
class SaveAlertFieldMappingOutput:
    dataset_name: str
    mappings: dict[str, str]
    updated_at: datetime

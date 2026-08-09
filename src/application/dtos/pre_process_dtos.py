from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class PreProcessAlertInput:
    alert_id: UUID
    payload: dict[str, Any]


@dataclass
class PreProcessAlertOutput:
    mandatory_fields: dict[str, Any]
    optional_fields: dict[str, Any]
    enrichment: dict[str, Any]
    pre_process_note: str

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class PostProcessAlertInput:
    alert_id: UUID
    workflow_started_at: datetime
    # The analyst's decision: block/pass/bidi/voicebot/scale_to_analyst -
    # this is what the executor step acted on, and what closes the alert.
    resolution_path: str


@dataclass
class PostProcessAlertOutput:
    status: str  # "success"
    resolution_path: str
    total_duration_seconds: float
    # ISO 8601, not datetime: this DTO gets dataclasses.asdict()'d
    # straight into a DynamoDB step record, which rejects raw datetimes.
    closed_at: str

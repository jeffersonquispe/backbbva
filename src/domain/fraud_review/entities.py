from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.domain.alerts.entities import Mark


class FraudLabelReviewChannel(StrEnum):
    """How a fraud-team label review was submitted."""

    UI = "ui"
    CSV = "csv"


@dataclass(frozen=True)
class FraudLabelReview:
    """Append-only record of one fraud-team review of an alert label."""

    id: UUID
    alert_id: UUID
    from_label: Mark
    to_label: Mark
    reviewed_by: str
    reviewed_at: datetime
    channel: FraudLabelReviewChannel
    note: str = ""

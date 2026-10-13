from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from src.application.ports.alert_port import Mark


class FraudLabelReviewChannel(StrEnum):
    """How the review reached ARIA (decision D2): the /historico-fraude UI
    action or the bulk CSV upload."""

    UI = "ui"
    CSV = "csv"


@dataclass(frozen=True)
class FraudLabelReview:
    """One fraud-team review of an alert's fraud_label - an audit row. A
    confirmation (from_label == to_label) is a review too."""

    id: UUID
    alert_id: UUID
    from_label: Mark
    to_label: Mark
    reviewed_by: str
    reviewed_at: datetime
    channel: FraudLabelReviewChannel
    note: str = ""


class FraudLabelReviewRepository(Protocol):
    """Append-only audit log (table fraud_label_reviews): a bank's business
    record, never overwritten - deliberately no update/delete."""

    def create(self, review: FraudLabelReview) -> FraudLabelReview: ...

    def list_by_alert(self, alert_id: UUID) -> list[FraudLabelReview]:
        """Oldest first."""
        ...

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.domain.fraud_review.entities import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)

__all__ = [
    "FraudLabelReview",
    "FraudLabelReviewChannel",
    "FraudLabelReviewRepository",
]


class FraudLabelReviewRepository(Protocol):
    """Append-only audit log (table fraud_label_reviews): a bank's business
    record, never overwritten - deliberately no update/delete."""

    def create(self, review: FraudLabelReview) -> FraudLabelReview: ...

    def list_by_alert(self, alert_id: UUID) -> list[FraudLabelReview]:
        """Oldest first."""
        ...

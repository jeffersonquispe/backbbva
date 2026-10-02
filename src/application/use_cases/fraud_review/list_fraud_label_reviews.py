from __future__ import annotations

from uuid import UUID

from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewRepository,
)


class ListFraudLabelReviews:
    """An alert's fraud_label audit trail, oldest first."""

    def __init__(self, review_repository: FraudLabelReviewRepository) -> None:
        self._reviews = review_repository

    def execute(self, alert_id: UUID) -> list[FraudLabelReview]:
        return self._reviews.list_by_alert(alert_id)

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
)
from src.domain.fraud_review.entities import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)


@dataclass
class ReviewFraudLabelInput:
    alert_id: UUID
    # "fraud" | "no_fraud" only - validated by the use case.
    fraud_label: str
    reviewed_by: str
    channel: FraudLabelReviewChannel
    note: str = ""


@dataclass
class ReviewFraudLabelOutput:
    review: FraudLabelReview
    snapshot: AlertMetricsSnapshot

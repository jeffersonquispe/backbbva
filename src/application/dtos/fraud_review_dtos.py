from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.alert_port import AlertMetricsSnapshot
from src.application.ports.fraud_label_review_port import (
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

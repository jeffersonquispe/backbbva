from datetime import UTC, datetime
from uuid import uuid4

from src.domain.alerts.entities import Mark
from src.domain.fraud_review.entities import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)


def test_fraud_label_review_records_confirmation_and_correction() -> None:
    now = datetime.now(UTC)
    alert_id = uuid4()
    correction = FraudLabelReview(
        id=uuid4(),
        alert_id=alert_id,
        from_label=Mark.NO_FRAUD,
        to_label=Mark.FRAUD,
        reviewed_by="fraud-reviewer",
        reviewed_at=now,
        channel=FraudLabelReviewChannel.UI,
        note="Confirmed by investigation",
    )
    confirmation = FraudLabelReview(
        id=uuid4(),
        alert_id=alert_id,
        from_label=Mark.FRAUD,
        to_label=Mark.FRAUD,
        reviewed_by="fraud-reviewer",
        reviewed_at=now,
        channel=FraudLabelReviewChannel.CSV,
    )

    assert correction.to_label is Mark.FRAUD
    assert correction.from_label is Mark.NO_FRAUD
    assert confirmation.from_label is confirmation.to_label

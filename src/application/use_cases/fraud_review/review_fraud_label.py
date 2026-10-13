"""ReviewFraudLabel (C5): the fraud team sets an alert's real outcome.

1. validate fraud_label (fraud | no_fraud only);
2. append an audit row to fraud_label_reviews (who, when, from -> to, note,
   channel) - append-only, a bank's business record;
3. RecordAlertMetricsEvent(FRAUD_REVIEWED): sets fraud_label,
   fraud_reviewed_at, fraud_review_count + 1 and applies the rollup delta
   (-old snapshot +new one), so the rollups only ever reflect the LAST
   value. A confirmation (same value) still fills fraud_reviewed_at and
   counts as a review, without moving false positives / undetected fraud.

The audit row is written first on purpose: if the metrics write then fails
(e.g. SnapshotVersionConflictError after its retries) the attempt is still
on record, and re-submitting simply appends another row."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.fraud_review_dtos import (
    ReviewFraudLabelInput,
    ReviewFraudLabelOutput,
)
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewRepository,
)
from src.application.ports.monitoring_port import (
    ATTR_ALERT_ID,
    ATTR_FRAUD_REVIEW_CHANNEL,
    ATTR_FRAUD_REVIEW_COUNT,
    ATTR_PREVIOUS_FRAUD_LABEL,
    MonitoringPort,
    span_dimension_attributes,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.entities import (
    Mark,
)
from src.domain.alerts.exceptions import AlertNotFoundError, InvalidFraudLabelError

REVIEWABLE_LABELS = frozenset({Mark.FRAUD, Mark.NO_FRAUD})
MAX_NOTE_LENGTH = 2000


def parse_fraud_label(value: str | None) -> Mark:
    normalized = (value or "").strip().lower()
    try:
        label = Mark(normalized)
    except ValueError as exc:
        raise InvalidFraudLabelError(value or "") from exc
    if label not in REVIEWABLE_LABELS:
        raise InvalidFraudLabelError(value or "")
    return label


class ReviewFraudLabel:
    def __init__(
        self,
        alert_repository: AlertRepository,
        review_repository: FraudLabelReviewRepository,
        record_metrics_event: RecordAlertMetricsEvent,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monitoring: MonitoringPort | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._reviews = review_repository
        self._record_metrics_event = record_metrics_event
        self._clock = clock
        # T2: one "fraud_label.review" span per review (optional).
        self._monitoring = monitoring

    def execute(self, input: ReviewFraudLabelInput) -> ReviewFraudLabelOutput:
        """Raises InvalidFraudLabelError / AlertNotFoundError."""
        if self._monitoring is None:
            return self._review(input)
        with self._monitoring.start(
            "fraud_label.review",
            "metrics.fraud_review",
            metadata={
                ATTR_ALERT_ID: str(input.alert_id),
                ATTR_FRAUD_REVIEW_CHANNEL: str(input.channel),
            },
        ) as span:
            output = self._review(input)
            # reviewed_by/note stay off the span: only the label change and
            # the alert's (non-identifying) dimensions.
            span.write_operation_metas(
                {
                    **span_dimension_attributes(output.snapshot),
                    ATTR_PREVIOUS_FRAUD_LABEL: str(output.review.from_label),
                    ATTR_FRAUD_REVIEW_COUNT: output.snapshot.fraud_review_count,
                }
            )
            return output

    def _review(self, input: ReviewFraudLabelInput) -> ReviewFraudLabelOutput:
        to_label = parse_fraud_label(input.fraud_label)
        alert = self._alerts.get(input.alert_id)
        if alert is None:
            raise AlertNotFoundError(str(input.alert_id))
        from_label = alert.metrics.fraud_label if alert.metrics else Mark.PENDING
        reviewed_at = self._clock()
        review = self._reviews.create(
            FraudLabelReview(
                id=uuid4(),
                alert_id=alert.id,
                from_label=from_label,
                to_label=to_label,
                reviewed_by=input.reviewed_by,
                reviewed_at=reviewed_at,
                channel=input.channel,
                note=(input.note or "").strip()[:MAX_NOTE_LENGTH],
            )
        )
        snapshot = self._record_metrics_event.execute(
            RecordAlertMetricsEventInput(
                alert_id=alert.id,
                event_type=AlertMetricsEventType.FRAUD_REVIEWED,
                occurred_at=reviewed_at,
                fraud_label=to_label,
            )
        )
        if snapshot is None:  # deleted between the read and the event
            raise AlertNotFoundError(str(input.alert_id))
        return ReviewFraudLabelOutput(review=review, snapshot=snapshot)

"""C5: ReviewFraudLabel + bulk CSV import, through the real
RecordAlertMetricsEvent and rollup diff, with in-memory fakes."""
from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.fraud_review_dtos import ReviewFraudLabelInput
from src.application.ports.alert_port import AlertRecord, AlertStatus, Mark
from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportStatus,
    FraudLabelReviewRowStatus,
)
from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)
from src.application.ports.metrics_rollup_port import RollupLevel
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.use_cases.fraud_review.import_fraud_label_reviews import (
    ImportFraudLabelReviews,
)
from src.application.use_cases.fraud_review.list_fraud_label_reviews import (
    ListFraudLabelReviews,
)
from src.application.use_cases.fraud_review.review_fraud_label import ReviewFraudLabel
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.exceptions import (
    AlertNotFoundError,
    InvalidFraudLabelError,
    SnapshotVersionConflictError,
)

TZ = "America/Bogota"
CREATED_AT = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)


class InMemoryMetricsRollupRepository:
    def __init__(self, alerts: InMemoryAlertRepository) -> None:
        self._alerts = alerts
        self.rows: dict = defaultdict(lambda: defaultdict(float))

    def apply(self, deltas, alert_guard) -> None:
        alert = self._alerts.get(alert_guard.alert_id)
        stored = alert.metrics.snapshot_version if alert and alert.metrics else 0
        if alert is None or stored != alert_guard.expected_version:
            raise SnapshotVersionConflictError(str(alert_guard.alert_id), alert_guard.expected_version)
        self._alerts.alerts[alert.id] = dataclasses.replace(alert, metrics=alert_guard.snapshot)
        for delta in deltas:
            for measure, value in delta.measures.items():
                self.rows[delta.key][measure] += value

    def query(self, data_type, level, periods, filters=None):
        raise NotImplementedError

    def total(self, measure: str, **dims) -> float:
        return sum(
            measures.get(measure, 0)
            for key, measures in self.rows.items()
            if key.level == RollupLevel.DAY
            and all(key.dimension(name) == value for name, value in dims.items())
        )


class InMemorySettings:
    def get(self) -> OperationalSettings:
        return OperationalSettings()


class InMemoryFraudLabelReviewRepository:
    """Append-only, like the real table: create + list only."""

    def __init__(self) -> None:
        self.rows: list[FraudLabelReview] = []

    def create(self, review: FraudLabelReview) -> FraudLabelReview:
        self.rows.append(review)
        return review

    def list_by_alert(self, alert_id: UUID) -> list[FraudLabelReview]:
        return sorted((r for r in self.rows if r.alert_id == alert_id), key=lambda r: r.reviewed_at)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def _setup():
    alerts = InMemoryAlertRepository()
    rollups = InMemoryMetricsRollupRepository(alerts)
    reviews = InMemoryFraudLabelReviewRepository()
    clock = Clock()
    recorder = RecordAlertMetricsEvent(alerts, rollups, InMemorySettings(), TZ, clock=clock)
    use_case = ReviewFraudLabel(alerts, reviews, recorder, clock=clock)
    return alerts, rollups, reviews, recorder, use_case


def _decided_alert(alerts, recorder, action: str) -> AlertRecord:
    alert = alerts.create(
        AlertRecord(
            id=uuid4(), event_id="e", event_type="payment", input={"channel": "WEB"},
            status=AlertStatus.CLOSED, created_at=CREATED_AT, updated_at=CREATED_AT,
        )
    )
    recorder.execute(RecordAlertMetricsEventInput(alert.id, AlertMetricsEventType.CREATED))
    recorder.execute(
        RecordAlertMetricsEventInput(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action=action,
            occurred_at=CREATED_AT + timedelta(minutes=2),
        )
    )
    return alert


def _review(alert_id, label, note="", channel=FraudLabelReviewChannel.UI):
    return ReviewFraudLabelInput(
        alert_id=alert_id, fraud_label=label, reviewed_by="fraud@aria.test", channel=channel, note=note
    )


def _fp(rollups) -> float:
    return rollups.total("count", mark="fraud", fraud_label="no_fraud")


def test_reviewing_twice_leaves_two_audit_rows_and_rollups_show_only_the_last_value() -> None:
    alerts, rollups, reviews, recorder, use_case = _setup()
    alert = _decided_alert(alerts, recorder, "block")  # mark = fraud

    first = use_case.execute(_review(alert.id, "no_fraud", note="customer recognized it"))
    assert (first.review.from_label, first.review.to_label) == (Mark.FRAUD, Mark.NO_FRAUD)
    assert _fp(rollups) == 1

    second = use_case.execute(_review(alert.id, "fraud", note="chargeback confirmed"))
    assert (second.review.from_label, second.review.to_label) == (Mark.NO_FRAUD, Mark.FRAUD)

    trail = ListFraudLabelReviews(reviews).execute(alert.id)
    assert [(r.from_label, r.to_label) for r in trail] == [
        (Mark.FRAUD, Mark.NO_FRAUD),
        (Mark.NO_FRAUD, Mark.FRAUD),
    ]
    assert [r.note for r in trail] == ["customer recognized it", "chargeback confirmed"]
    assert all(r.reviewed_by == "fraud@aria.test" for r in trail)

    snapshot = alerts.get(alert.id).metrics
    assert snapshot.fraud_label == Mark.FRAUD and snapshot.fraud_review_count == 2
    assert snapshot.fraud_reviewed_at == second.review.reviewed_at
    # Only the last value counts: no false positive left, one true positive,
    # one reviewed alert (two review events).
    assert _fp(rollups) == 0
    assert rollups.total("count") == 1
    assert rollups.total("count", mark="fraud", fraud_label="fraud") == 1
    assert rollups.total("reviewed_count") == 1
    assert rollups.total("review_events") == 2
    assert rollups.total("reviewed_confirmed_count") == 1
    assert rollups.total("reviewed_changed_count") == 0


def test_a_confirmation_fills_fraud_reviewed_at_without_moving_false_positives() -> None:
    alerts, rollups, reviews, recorder, use_case = _setup()
    alert = _decided_alert(alerts, recorder, "block")
    assert alerts.get(alert.id).metrics.fraud_reviewed_at is None
    fp_before = _fp(rollups)
    undetected_before = rollups.total("count", mark="no_fraud", fraud_label="fraud")

    output = use_case.execute(_review(alert.id, "fraud"))

    assert output.review.from_label == output.review.to_label == Mark.FRAUD
    assert output.snapshot.fraud_reviewed_at is not None
    assert output.snapshot.fraud_review_count == 1
    assert _fp(rollups) == fp_before == 0
    assert rollups.total("count", mark="no_fraud", fraud_label="fraud") == undetected_before
    assert rollups.total("reviewed_confirmed_count") == 1
    assert len(reviews.rows) == 1


@pytest.mark.parametrize("label", ["pending", "maybe", ""])
def test_only_fraud_or_no_fraud_is_accepted(label: str) -> None:
    alerts, _, reviews, recorder, use_case = _setup()
    alert = _decided_alert(alerts, recorder, "none")
    with pytest.raises(InvalidFraudLabelError):
        use_case.execute(_review(alert.id, label))
    assert reviews.rows == []


def test_unknown_alert_is_not_found_and_leaves_no_audit_row() -> None:
    _, _, reviews, _, use_case = _setup()
    with pytest.raises(AlertNotFoundError):
        use_case.execute(_review(uuid4(), "fraud"))
    assert reviews.rows == []


def test_csv_import_reports_each_row_and_bad_rows_do_not_abort_the_batch() -> None:
    alerts, rollups, reviews, recorder, use_case = _setup()
    a = _decided_alert(alerts, recorder, "block")
    b = _decided_alert(alerts, recorder, "none")
    missing = uuid4()
    content = (
        "﻿Alert_ID;Fraud_Label;Note\n"
        f"{a.id};NO_FRAUD;cliente reconoce\n"
        "not-a-uuid;fraud;\n"
        f"{b.id};pending;\n"
        "\n"
        f"{missing};fraud;\n"
        f"{b.id};fraud;contracargo\n"
    ).encode("utf-8")

    result = ImportFraudLabelReviews(use_case).execute(content, reviewed_by="bulk@aria.test")

    assert result.status == FraudLabelReviewImportStatus.READY
    assert (result.total, result.applied, result.failed) == (5, 2, 3)
    assert [(r.row, r.status) for r in result.rows] == [
        (1, FraudLabelReviewRowStatus.APPLIED),
        (2, FraudLabelReviewRowStatus.INVALID),
        (3, FraudLabelReviewRowStatus.INVALID),
        (4, FraudLabelReviewRowStatus.NOT_FOUND),
        (5, FraudLabelReviewRowStatus.APPLIED),
    ]
    assert {r.channel for r in reviews.rows} == {FraudLabelReviewChannel.CSV}
    assert [r.note for r in reviews.rows] == ["cliente reconoce", "contracargo"]
    assert alerts.get(a.id).metrics.fraud_label == Mark.NO_FRAUD
    assert alerts.get(b.id).metrics.fraud_label == Mark.FRAUD
    assert _fp(rollups) == 1
    assert rollups.total("count", mark="no_fraud", fraud_label="fraud") == 1


def test_csv_without_required_columns_fails_as_a_whole() -> None:
    _, _, reviews, _, use_case = _setup()
    result = ImportFraudLabelReviews(use_case).execute(b"id,label\n1,fraud\n", reviewed_by="x")
    assert result.status == FraudLabelReviewImportStatus.FAILED
    assert "alert_id" in result.error and "fraud_label" in result.error
    assert reviews.rows == []


# --- T2: one "fraud_label.review" span per review ------------------------------


class RecordingSpan(MonitoringSpan):
    def __init__(self, metadata: dict) -> None:
        self.attributes = dict(metadata)
        self.error: str | None = None

    def write_input(self, data): ...
    def write_result(self, data): ...
    def write_inner_logs(self, entries): ...
    def record_dependency(self, name, kind, metadata=None): ...

    def write_operation_metas(self, metadata):
        self.attributes.update(metadata)

    def finish(self, error=None):
        self.error = error


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.spans: list[tuple[str, RecordingSpan]] = []

    def start(self, operation_name, operation_type, metadata=None):
        span = RecordingSpan(metadata or {})
        self.spans.append((operation_name, span))
        return span


def test_each_review_emits_a_fraud_label_review_span() -> None:
    alerts, rollups, reviews, recorder, _ = _setup()
    monitoring = RecordingMonitoring()
    use_case = ReviewFraudLabel(alerts, reviews, recorder, clock=Clock(), monitoring=monitoring)
    alert = _decided_alert(alerts, recorder, "block")

    use_case.execute(_review(alert.id, "no_fraud", channel=FraudLabelReviewChannel.CSV))
    use_case.execute(_review(alert.id, "no_fraud"))

    assert [name for name, _ in monitoring.spans] == ["fraud_label.review"] * 2
    first, second = (span for _, span in monitoring.spans)
    assert first.attributes["alert_id"] == str(alert.id)
    assert first.attributes["aria.fraud_label"] == "no_fraud"
    assert first.attributes["aria.fraud_label.previous"] == "fraud"
    assert first.attributes["aria.mark"] == "fraud"
    assert first.attributes["aria.fraud_review.channel"] == "csv"
    assert first.attributes["aria.fraud_review.count"] == 1
    assert second.attributes["aria.fraud_label.previous"] == "no_fraud"
    assert second.attributes["aria.fraud_review.count"] == 2
    # Who reviewed and their note never reach the span.
    assert "fraud@aria.test" not in second.attributes.values()


def test_a_failed_review_span_carries_the_error() -> None:
    alerts, _, reviews, recorder, _ = _setup()
    monitoring = RecordingMonitoring()
    use_case = ReviewFraudLabel(alerts, reviews, recorder, monitoring=monitoring)

    with pytest.raises(AlertNotFoundError):
        use_case.execute(_review(uuid4(), "fraud"))

    [(_, span)] = monitoring.spans
    assert span.error is not None

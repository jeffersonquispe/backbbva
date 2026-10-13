"""API contract of /alerts/history, /alerts/{id}/fraud-review(s) and the
bulk review CSV - permissions, status codes, wire field names."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

os.environ.setdefault("GENAI_ENVIRONMENT", "test")
os.environ.setdefault("API_V0_STR", "/api/v0")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.dtos.alert_history_dtos import (
    AlertHistoryItem,
    ListAlertHistoryOutput,
)
from src.application.dtos.fraud_review_dtos import ReviewFraudLabelOutput
from src.application.ports.alert_port import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportResult,
    FraudLabelReviewImportStatus,
    FraudLabelReviewRowResult,
    FraudLabelReviewRowStatus,
)
from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.fraud_review.review_fraud_label import parse_fraud_label
from src.domain.alerts.exceptions import AlertNotFoundError
from src.infrastructure.entrypoint.api.factories import (
    fraud_review_factory as factories,
)
from src.infrastructure.entrypoint.api.routers import alerts_router
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
KNOWN = uuid4()


def _user(role: LocalRole) -> LocalUser:
    return LocalUser(
        id=uuid4(), email=f"{role.value}@aria.test", name=role.value, password_hash="x",
        role=role, is_active=True, created_at=NOW, updated_at=NOW,
    )


class RecordingReviewFraudLabel:
    def __init__(self) -> None:
        self.inputs = []

    def execute(self, input):
        self.inputs.append(input)
        label = parse_fraud_label(input.fraud_label)
        if input.alert_id != KNOWN:
            raise AlertNotFoundError(str(input.alert_id))
        review = FraudLabelReview(
            id=uuid4(), alert_id=input.alert_id, from_label=Mark.FRAUD, to_label=label,
            reviewed_by=input.reviewed_by, reviewed_at=NOW, channel=input.channel, note=input.note,
        )
        snapshot = AlertMetricsSnapshot(
            mark=Mark.FRAUD, fraud_label=label, marked_at=NOW - timedelta(days=1),
            fraud_reviewed_at=NOW, fraud_review_count=1, snapshot_version=4,
        )
        return ReviewFraudLabelOutput(review=review, snapshot=snapshot)


class RecordingListHistory:
    def __init__(self) -> None:
        self.inputs = []

    def execute(self, input):
        self.inputs.append(input)
        alert = AlertRecord(
            id=KNOWN, event_id="evt", event_type="payment", input={}, status=AlertStatus.CLOSED,
            created_at=NOW, updated_at=NOW, customer_id="c-1",
        )
        snapshot = AlertMetricsSnapshot(
            channel="WEB", amount=12.5, amount_tier="low", schema_version=2,
            resolution_method=AlertResolutionMethod.ANALYST, mark=Mark.FRAUD,
            fraud_label=Mark.NO_FRAUD, marked_at=NOW, fraud_reviewed_at=NOW,
            fraud_review_count=2, resolution_time_seconds=180.0, status=AlertStatus.CLOSED,
        )
        return ListAlertHistoryOutput(items=[AlertHistoryItem(alert, snapshot, True)], next_cursor="abc")


class RecordingUpload:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, content: bytes, reviewed_by: str) -> str:
        self.calls.append((content, reviewed_by))
        return "task-1"


class FixedImportStatus:
    def execute(self, task_id: str):
        return FraudLabelReviewImportResult(
            status=FraudLabelReviewImportStatus.READY, total=2, applied=1, failed=1,
            rows=[
                FraudLabelReviewRowResult(1, str(KNOWN), "fraud", FraudLabelReviewRowStatus.APPLIED),
                FraudLabelReviewRowResult(2, "x", "fraud", FraudLabelReviewRowStatus.INVALID, "bad uuid"),
            ],
        )


class FixedReviewTrail:
    def execute(self, alert_id: UUID):
        return [
            FraudLabelReview(uuid4(), alert_id, Mark.FRAUD, Mark.NO_FRAUD, "a@x", NOW, FraudLabelReviewChannel.CSV, "n"),
        ]


def _client(role: LocalRole):
    review, history, upload = RecordingReviewFraudLabel(), RecordingListHistory(), RecordingUpload()
    app = FastAPI()
    app.include_router(alerts_router.router, prefix="/api/v0")
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    app.dependency_overrides[factories.get_review_fraud_label_use_case] = lambda: review
    app.dependency_overrides[factories.get_list_alert_history_use_case] = lambda: history
    app.dependency_overrides[factories.get_upload_fraud_label_review_import_use_case] = lambda: upload
    app.dependency_overrides[factories.get_get_fraud_label_review_import_use_case] = FixedImportStatus
    app.dependency_overrides[factories.get_list_fraud_label_reviews_use_case] = FixedReviewTrail
    return TestClient(app), review, history, upload


def test_review_records_the_authenticated_reviewer_and_returns_the_new_snapshot() -> None:
    client, review, _, _ = _client(LocalRole.MANAGER)

    response = client.post(
        f"/api/v0/alerts/{KNOWN}/fraud-review", json={"fraud_label": "no_fraud", "note": "ok"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"review", "mark", "fraud_label", "marked_at", "fraud_reviewed_at", "fraud_review_count"}
    assert body["review"]["channel"] == "ui"
    assert body["review"]["reviewed_by"] == "manager@aria.test"
    assert (body["review"]["from_label"], body["review"]["to_label"]) == ("fraud", "no_fraud")
    assert body["fraud_label"] == "no_fraud" and body["fraud_review_count"] == 1
    assert review.inputs[0].channel == FraudLabelReviewChannel.UI


def test_review_status_codes() -> None:
    client, _, _, _ = _client(LocalRole.MANAGER)
    assert client.post(f"/api/v0/alerts/{uuid4()}/fraud-review", json={"fraud_label": "fraud"}).status_code == 404
    assert client.post(f"/api/v0/alerts/{KNOWN}/fraud-review", json={"fraud_label": "pending"}).status_code == 422


def test_review_and_bulk_csv_need_the_fraud_review_permission() -> None:
    # release_manager sees the history but may not review.
    client, review, _, upload = _client(LocalRole.RELEASE_MANAGER)
    assert client.post(f"/api/v0/alerts/{KNOWN}/fraud-review", json={"fraud_label": "fraud"}).status_code == 403
    files = {"file": ("r.csv", b"alert_id,fraud_label,note\n", "text/csv")}
    assert client.post("/api/v0/alerts/fraud-review-imports", files=files).status_code == 403
    assert client.get("/api/v0/alerts/history").status_code == 200
    assert review.inputs == [] and upload.calls == []
    # fraud_analyst has neither fraud_history nor fraud_review.
    client, _, _, _ = _client(LocalRole.FRAUD_ANALYST)
    assert client.get("/api/v0/alerts/history").status_code == 403


def test_history_passes_filters_and_returns_snapshot_fields() -> None:
    client, _, history, _ = _client(LocalRole.MANAGER)

    response = client.get(
        "/api/v0/alerts/history",
        params=[("from", "2026-09-01T00:00:00-05:00"), ("channel", "WEB"), ("channel", "APP"),
                ("status", "CLOSED"), ("limit", "20"), ("cursor", "c1")],
    )

    assert response.status_code == 200, response.text
    sent = history.inputs[0]
    assert sent.filters == {"channel": ["WEB", "APP"], "status": ["CLOSED"]}
    assert (sent.limit, sent.cursor) == (20, "c1")
    body = response.json()
    assert body["next_cursor"] == "abc"
    item = body["items"][0]
    assert item["alert_id"] == str(KNOWN)
    assert (item["mark"], item["fraud_label"], item["fraud_review_count"]) == ("fraud", "no_fraud", 2)
    assert item["resolution_method"] == "analyst" and item["has_snapshot"] is True
    assert {"marked_at", "fraud_reviewed_at", "amount_tier", "schema_version"} <= set(item)


def test_bulk_csv_dispatches_and_reports_per_row() -> None:
    client, _, _, upload = _client(LocalRole.CHANNEL_MANAGER)

    bad = client.post("/api/v0/alerts/fraud-review-imports", files={"file": ("r.xlsx", b"x", "application/octet-stream")})
    assert bad.status_code == 400

    content = f"alert_id,fraud_label,note\n{KNOWN},fraud,\n".encode()
    response = client.post("/api/v0/alerts/fraud-review-imports", files={"file": ("r.csv", content, "text/csv")})
    assert response.status_code == 202
    assert response.json() == {"task_id": "task-1", "status": "PENDING"}
    assert upload.calls == [(content, "channel_manager@aria.test")]

    status = client.get("/api/v0/alerts/fraud-review-imports/task-1").json()
    assert (status["status"], status["total"], status["applied"], status["failed"]) == ("READY", 2, 1, 1)
    assert status["rows"][1] == {
        "row": 2, "alert_id": "x", "fraud_label": "fraud", "status": "invalid", "error": "bad uuid",
    }


def test_review_trail() -> None:
    client, _, _, _ = _client(LocalRole.MANAGER)
    trail = client.get(f"/api/v0/alerts/{KNOWN}/fraud-reviews").json()
    assert trail[0]["channel"] == "csv" and trail[0]["to_label"] == "no_fraud"

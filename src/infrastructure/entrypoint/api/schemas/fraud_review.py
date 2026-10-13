from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# --- Fraud history (A3) + fraud_label review (C5) ----------------------------


class AlertHistoryItemSchema(BaseModel):
    alert_id: UUID
    event_id: str
    event_type: str
    # Live alert status (the metrics "status" filter matches the snapshot's).
    status: str
    customer_id: str | None
    created_at: datetime
    updated_at: datetime
    # False = no metrics event touched this alert yet; the fields below are
    # then derived from canonical input (mark/fraud_label "pending").
    has_snapshot: bool
    origin: str | None
    segment: str | None
    channel: str | None
    subchannel: str | None
    amount: float | None
    amount_tier: str
    schema_version: int | None
    configuration_id: str | None
    resolution_method: Literal["aria", "analyst", "voicebot", "bidi"] | None
    mark: Literal["fraud", "no_fraud", "pending"]
    fraud_label: Literal["fraud", "no_fraud", "pending"]
    marked_at: datetime | None
    fraud_reviewed_at: datetime | None
    fraud_review_count: int
    resolution_time_seconds: float | None


class AlertHistoryPageResponse(BaseModel):
    items: list[AlertHistoryItemSchema]
    # Opaque - pass back as ?cursor= for the next page; null = no more.
    next_cursor: str | None


class FraudReviewRequest(BaseModel):
    fraud_label: Literal["fraud", "no_fraud"]
    note: str = Field(default="", max_length=2000)


class FraudLabelReviewSchema(BaseModel):
    id: UUID
    alert_id: UUID
    from_label: Literal["fraud", "no_fraud", "pending"]
    to_label: Literal["fraud", "no_fraud"]
    reviewed_by: str
    reviewed_at: datetime
    channel: Literal["ui", "csv"]
    note: str


class FraudReviewResponse(BaseModel):
    review: FraudLabelReviewSchema
    # The alert's snapshot after the review.
    mark: Literal["fraud", "no_fraud", "pending"]
    fraud_label: Literal["fraud", "no_fraud", "pending"]
    marked_at: datetime | None
    fraud_reviewed_at: datetime | None
    fraud_review_count: int


class FraudLabelReviewRowResultSchema(BaseModel):
    row: int
    alert_id: str
    fraud_label: str
    status: Literal["applied", "invalid", "not_found", "error"]
    error: str | None = None


class UploadFraudLabelReviewImportResponse(BaseModel):
    task_id: str
    status: Literal["PENDING", "READY", "FAILED"]


class FraudLabelReviewImportResponse(BaseModel):
    task_id: str
    status: Literal["PENDING", "READY", "FAILED"]
    total: int
    applied: int
    failed: int
    rows: list[FraudLabelReviewRowResultSchema]
    error: str | None = None


class LiveAlertFunnelResponse(BaseModel):
    received: int
    processing: int
    escalated: int
    voicebot_in_call: int
    measured_at: datetime


class VersionEventResponse(BaseModel):
    kind: Literal["schema", "configuration"]
    label: str
    version: int
    configuration_id: str | None = None
    at: datetime

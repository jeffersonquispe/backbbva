from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class AlertStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AlertOrigin(StrEnum):
    MANUAL = "manual"
    TEST_RUN = "test_run"
    OPTIMIZER_EVALUATION = "optimizer_evaluation"
    SIMULATOR = "simulator"
    PRODUCTION = "production"


PROCESSED_WHILE_AGENT_OFF = frozenset(
    {AlertOrigin.MANUAL, AlertOrigin.TEST_RUN, AlertOrigin.OPTIMIZER_EVALUATION}
)


class Mark(StrEnum):
    FRAUD = "fraud"
    NO_FRAUD = "no_fraud"
    PENDING = "pending"


class AlertResolutionMethod(StrEnum):
    ARIA = "aria"
    ANALYST = "analyst"
    VOICEBOT = "voicebot"
    BIDI = "bidi"


@dataclass(frozen=True)
class AlertMetricsSnapshot:
    origin: str | None = None
    segment: str | None = None
    channel: str | None = None
    subchannel: str | None = None
    amount: float | None = None
    amount_tier: str = "unknown"
    schema_version: int | None = None
    configuration_id: str | None = None
    resolution_method: AlertResolutionMethod | None = None
    mark: Mark = Mark.PENDING
    fraud_label: Mark = Mark.PENDING
    marked_at: datetime | None = None
    fraud_reviewed_at: datetime | None = None
    fraud_review_count: int = 0
    resolution_time_seconds: float | None = None
    status: AlertStatus | None = None
    snapshot_version: int = 0


@dataclass
class AlertRecord:
    id: UUID
    event_id: str
    event_type: str
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
    raw_payload_ref: Any | None = None
    schema_version: int | None = None
    input: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)
    history_prev_alerta: list[dict[str, Any]] = field(default_factory=list)
    agent_output: dict[str, Any] = field(default_factory=dict)
    agent_output_ref: Any | None = None
    customer_id: str | None = None
    async_operation_id: UUID | None = None
    workflow_execution_id: UUID | None = None
    configuration_id: str | None = None
    configuration_version: int | None = None
    metrics: AlertMetricsSnapshot | None = None
    # How a human analyst closed an escalated alert: decision, notes,
    # resolved_by (user id) and resolved_at. Stored on the alert so the
    # detail of a CLOSED alert needs no scan of the reservation audit trail.
    analyst_resolution: dict[str, Any] = field(default_factory=dict)

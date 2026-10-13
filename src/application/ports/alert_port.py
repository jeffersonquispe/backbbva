from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class AlertStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    # Workflow finished by escalating to a human analyst - waits in the
    # analyst queue until someone takes and resolves it (then CLOSED).
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    # Not processed: the agent was switched off and the alert's origin is
    # one that must not run while it is off (see AlertOrigin).
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AlertOrigin(StrEnum):
    """Where an alert entered the pipeline. Decides what happens while the
    agent is switched off (OperationalSettings.agent_enabled = False):
    MANUAL and TEST_RUN still process, SIMULATOR and PRODUCTION are skipped."""

    MANUAL = "manual"
    TEST_RUN = "test_run"
    SIMULATOR = "simulator"
    PRODUCTION = "production"


PROCESSED_WHILE_AGENT_OFF = frozenset({AlertOrigin.MANUAL, AlertOrigin.TEST_RUN})


class Mark(StrEnum):
    """The decision taken on an alert (by ARIA, an analyst or the voicebot)
    and, as fraud_label, the case's real outcome. PENDING = no fraud/no-fraud
    decision yet (escalated, bidi, voicebot awaiting its callback, failed,
    skipped); it is excluded from false-positive / undetected-fraud
    measures. Once mark leaves PENDING it never changes."""

    FRAUD = "fraud"
    NO_FRAUD = "no_fraud"
    PENDING = "pending"


class AlertResolutionMethod(StrEnum):
    """Who/which channel resolves the case - a metrics dimension. Not the
    admin-editable "Resolución" catalog (resolution_method_catalog_port.py)."""

    ARIA = "aria"
    ANALYST = "analyst"
    VOICEBOT = "voicebot"
    BIDI = "bidi"


@dataclass(frozen=True)
class AlertMetricsSnapshot:
    """The dimensions and measures this alert has already contributed to the
    metrics rollups (metrics_rollup_port.py). Every later change is applied
    as a delta (-this snapshot, +the new one), so the rollups never need a
    recount. Written ONLY by RecordAlertMetricsEvent, in the same DynamoDB
    transaction as the rollup deltas, guarded by snapshot_version."""

    origin: str | None = None
    segment: str | None = None
    channel: str | None = None
    subchannel: str | None = None
    amount: float | None = None
    # Frozen when the alert arrives - see domain/alerts/amount_tiers.py.
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
    # 0 = never written. Each successful write stores previous + 1.
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
    # The exact configuration the workflow resolved for this alert (the
    # active one, or a test run's pinned configuration_ref), set right after
    # pre_process. None until then, or when no configuration was active.
    configuration_id: str | None = None
    configuration_version: int | None = None
    # None for alerts no metrics event has touched yet (incl. every alert
    # created before the metrics snapshot existed).
    metrics: AlertMetricsSnapshot | None = None


class AlertRepository(Protocol):
    def create(self, alert: AlertRecord) -> AlertRecord: ...

    def get(self, alert_id: UUID) -> AlertRecord | None: ...

    def update(
        self,
        alert_id: UUID,
        *,
        status: AlertStatus | None = None,
        async_operation_id: UUID | None = None,
        workflow_execution_id: UUID | None = None,
        configuration_id: str | None = None,
        configuration_version: int | None = None,
        schema_version: int | None = None,
        input: dict[str, Any] | None = None,
        labels: dict[str, Any] | None = None,
        history_prev_alerta: list[dict[str, Any]] | None = None,
        agent_output: dict[str, Any] | None = None,
        agent_output_ref: Any | None = None,
    ) -> AlertRecord | None: ...

    def delete(self, alert_id: UUID) -> None: ...

    def list_by_status(self, status: AlertStatus) -> list[AlertRecord]:
        """Oldest first - e.g. the ESCALATED alerts waiting in the analyst
        queue."""
        ...

    def count_by_status(self, status: AlertStatus) -> int:
        """How many alerts are in this status right now - the live funnel
        (R9). Served by a status index, never a Scan; may lag a status
        change by the index's propagation delay (sub-second)."""
        ...

    def list_by_created_day(self, created_day: date) -> list[AlertRecord]:
        """Alerts whose created_at falls on this calendar day in the
        operations timezone (Bogota), oldest first - served by an index,
        never a Scan (reconciliation, backfill, fraud history)."""
        ...

    def page_by_created_day(
        self, created_day: date, *, before: datetime | None, limit: int
    ) -> list[AlertRecord]:
        """Up to `limit` alerts of this operations-timezone day, NEWEST
        first, with created_at strictly before `before` (None = from the
        day's end) - the fraud history page reads a day in slices through
        the same index instead of loading the whole day."""
        ...

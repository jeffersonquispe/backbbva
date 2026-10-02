from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.application.ports.alert_port import AlertStatus, Mark


class AlertMetricsEventType(StrEnum):
    """The points in an alert's life that change its metrics snapshot."""

    # Alert stored: origin, channel, subchannel, amount, frozen amount tier,
    # configuration_id (when the caller pinned one).
    CREATED = "created"
    # End of pre_process: segment, and the configuration actually resolved.
    PRE_PROCESSED = "pre_processed"
    # Workflow ended (CLOSED / ESCALATED / FAILED / SKIPPED): mark from the
    # executor's action, resolution_method, marked_at, resolution time.
    WORKFLOW_FINISHED = "workflow_finished"
    # Human analyst resolved an escalated alert (block / pass / bidi).
    ANALYST_RESOLVED = "analyst_resolved"
    # Voicebot provider callback with the call's outcome.
    VOICEBOT_COMPLETED = "voicebot_completed"
    # Fraud team reviewed fraud_label (C5) - a confirmation counts too.
    FRAUD_REVIEWED = "fraud_reviewed"


@dataclass
class RecordAlertMetricsEventInput:
    alert_id: UUID
    event_type: AlertMetricsEventType
    # Defaults to the use case's clock.
    occurred_at: datetime | None = None
    # CREATED
    origin: str | None = None
    # CREATED / PRE_PROCESSED
    configuration_id: str | None = None
    # PRE_PROCESSED
    segment: str | None = None
    # WORKFLOW_FINISHED: the alert's final status for this run.
    status: AlertStatus | None = None
    # WORKFLOW_FINISHED: the executor's executed_action ("none", "block",
    # "bidi", "voicebot", "scale_to_analyst") or "discarded" for a
    # deterministic-rule discard; None when the run failed/was skipped.
    executed_action: str | None = None
    # ANALYST_RESOLVED: "block" | "pass" | "bidi".
    decision: str | None = None
    # VOICEBOT_COMPLETED: the provider's free-text outcome.
    outcome: str | None = None
    # FRAUD_REVIEWED
    fraud_label: Mark | None = None

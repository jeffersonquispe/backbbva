from __future__ import annotations

from dataclasses import dataclass, field

from src.application.ports.alert_port import AlertRecord
from src.application.ports.resource_reservation_port import ResourceReservation
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStepExecutionRecord,
)

# What a human analyst can resolve an escalated alert with. block/bidi are
# dispatched as channel actions (same AlertActionDispatcher the executor
# uses); pass releases the alert with no action.
VALID_ANALYST_RESOLUTIONS = ("block", "pass", "bidi")


@dataclass
class AnalystQueueItem:
    alert: AlertRecord
    # The analyst currently working on it, None while nobody has taken it
    # (or their 30-minute reservation expired).
    reservation: ResourceReservation | None = None


@dataclass
class AlertDetail:
    alert: AlertRecord
    reservation: ResourceReservation | None = None
    workflow: WorkflowExecutionRecord | None = None
    steps: list[WorkflowStepExecutionRecord] = field(default_factory=list)


@dataclass
class ResolveEscalatedAlertInput:
    alert_id: str
    analyst_id: str
    decision: str  # one of VALID_ANALYST_RESOLUTIONS
    notes: str = ""

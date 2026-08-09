from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.aric_alert_port import AricAlertSignals


@dataclass
class EscalateAlertToAnalystInput:
    alert_id: UUID
    event_id: str
    session_id: str | None
    reason: str


@dataclass
class EscalateAlertToAnalystOutput:
    alert_id: UUID
    reason: str
    aric_signals: AricAlertSignals

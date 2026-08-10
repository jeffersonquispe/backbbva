from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

# The three executor actions dispatched as async channel actions - "pass"
# is a no-op and "scale_to_analyst" goes through the existing
# AnalystEscalationDispatcher, neither reaches this use case.
VALID_EXECUTOR_ACTIONS = ("block", "bidi", "voicebot")


@dataclass
class ExecuteAlertActionInput:
    action: str
    alert_id: UUID


@dataclass
class ExecuteAlertActionOutput:
    action: str
    detail: str

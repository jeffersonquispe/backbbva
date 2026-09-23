from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass
class DiscardAlertInput:
    alert_id: UUID
    reason: str
    rule_id: str | None = None
    decision: str | None = None
    aric_action: str | None = None


@dataclass
class DiscardAlertOutput:
    logged: bool = True

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AlertActionResult:
    action: str
    detail: str


class AlertChannelActionPort:
    """Executes the channel action the analyst decided on. Each method is
    one branch of the executor step's block/bidi/voicebot case - "pass" is
    a no-op that never reaches this port, and "scale_to_analyst" goes
    through AnalystEscalationDispatcher instead (a human analyst, not a
    channel)."""

    def block(self, alert_id: UUID) -> AlertActionResult:
        raise NotImplementedError

    def route_to_bidi(self, alert_id: UUID) -> AlertActionResult:
        raise NotImplementedError

    def route_to_voicebot(self, alert_id: UUID) -> AlertActionResult:
        raise NotImplementedError

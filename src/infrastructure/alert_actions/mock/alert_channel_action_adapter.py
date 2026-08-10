from __future__ import annotations

import time
from uuid import UUID

from src.application.ports.alert_action_port import (
    AlertActionResult,
    AlertChannelActionPort,
)


class MockAlertChannelActionAdapter(AlertChannelActionPort):
    def block(self, alert_id: UUID) -> AlertActionResult:
        time.sleep(0.05)
        return AlertActionResult(
            action="block",
            detail=f"Blocked the transaction/channel for alert {alert_id}.",
        )

    def route_to_bidi(self, alert_id: UUID) -> AlertActionResult:
        time.sleep(0.05)
        return AlertActionResult(
            action="bidi",
            detail=(
                f"Routed alert {alert_id} to the bidirectional "
                "verification channel."
            ),
        )

    def route_to_voicebot(self, alert_id: UUID) -> AlertActionResult:
        time.sleep(0.05)
        return AlertActionResult(
            action="voicebot",
            detail=f"Routed alert {alert_id} to the voicebot verification channel.",
        )

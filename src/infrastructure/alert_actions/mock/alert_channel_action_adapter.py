from __future__ import annotations

import time
from uuid import UUID

from src.application.ports.alert_action_port import (
    AlertActionResult,
    AlertChannelActionPort,
)


class MockAlertChannelActionAdapter(AlertChannelActionPort):
    def block(self, alert_id: UUID, comment: str | None = None) -> AlertActionResult:
        time.sleep(0.05)
        detail = f"Blocked the transaction/channel for alert {alert_id}."
        if comment:
            detail += f" ARIC comment: {comment}"
        return AlertActionResult(action="block", detail=detail)

    def route_to_bidi(
        self, alert_id: UUID, comment: str | None = None
    ) -> AlertActionResult:
        time.sleep(0.05)
        detail = f"Routed alert {alert_id} to the bidirectional verification channel."
        if comment:
            detail += f" ARIC comment: {comment}"
        return AlertActionResult(action="bidi", detail=detail)

    def route_to_voicebot(
        self, alert_id: UUID, script: str | None = None
    ) -> AlertActionResult:
        time.sleep(0.05)
        detail = f"Routed alert {alert_id} to the voicebot verification channel."
        if script:
            detail += f" Script: {script}"
        return AlertActionResult(action="voicebot", detail=detail)

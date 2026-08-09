from __future__ import annotations

import time

from src.application.ports.aric_alert_port import AricAlertPort, AricAlertSignals


class MockAricAlertAdapter(AricAlertPort):
    def fetch_signals(
        self,
        event_id: str,
        session_id: str | None,
    ) -> AricAlertSignals:
        time.sleep(0.05)
        return AricAlertSignals(
            is_mobile_rat=False,
            is_emulator_rat=False,
            is_rat=False,
            is_bot=False,
            is_on_call_active=False,
        )

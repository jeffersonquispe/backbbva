from __future__ import annotations

import dataclasses

from src.application.dtos.escalate_alert_dtos import (
    EscalateAlertToAnalystInput,
    EscalateAlertToAnalystOutput,
)
from src.application.ports.aric_alert_port import AricAlertPort
from src.application.ports.monitoring_port import MonitoringPort


class EscalateAlertToAnalystUseCase:
    def __init__(
        self,
        aric_alert_port: AricAlertPort,
        monitoring: MonitoringPort,
    ) -> None:
        self._aric = aric_alert_port
        self._monitoring = monitoring

    def execute(
        self, input: EscalateAlertToAnalystInput
    ) -> EscalateAlertToAnalystOutput:
        with self._monitoring.start(
            "escalate_alert_to_analyst",
            "workflow.escalation",
            metadata={"alert_id": str(input.alert_id), "reason": input.reason},
        ) as span:
            span.write_input({"event_id": input.event_id, "reason": input.reason})
            aric_signals = self._aric.fetch_signals(input.event_id, input.session_id)
            span.record_dependency("aric", "http", {"event_id": input.event_id})
            span.write_result({"aric_signals": dataclasses.asdict(aric_signals)})
            return EscalateAlertToAnalystOutput(
                alert_id=input.alert_id,
                reason=input.reason,
                aric_signals=aric_signals,
            )

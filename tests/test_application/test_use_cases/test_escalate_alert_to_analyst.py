from __future__ import annotations

import uuid
from typing import Any

from src.application.dtos.escalate_alert_dtos import EscalateAlertToAnalystInput
from src.application.ports.aric_alert_port import AricAlertPort, AricAlertSignals
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.use_cases.alerts.escalate_alert_to_analyst import (
    EscalateAlertToAnalystUseCase,
)


class RecordingAricAlertPort(AricAlertPort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def fetch_signals(self, event_id, session_id) -> AricAlertSignals:
        self.calls.append((event_id, session_id))
        return AricAlertSignals(is_rat=True, is_bot=False)


class RecordingMonitoringSpan(MonitoringSpan):
    def __init__(self, recorder: list[str]) -> None:
        self._recorder = recorder

    def write_input(self, data: dict[str, Any]) -> None:
        self._recorder.append("write_input")

    def write_result(self, data: dict[str, Any]) -> None:
        self._recorder.append("write_result")

    def write_inner_logs(self, entries) -> None:
        self._recorder.append("write_inner_logs")

    def write_operation_metas(self, metadata: dict[str, Any]) -> None:
        self._recorder.append("write_operation_metas")

    def record_dependency(self, name, kind, metadata=None) -> None:
        self._recorder.append(f"dependency:{name}")

    def finish(self, error: str | None = None) -> None:
        self._recorder.append(f"finish:{error}")


class RecordingMonitoringPort(MonitoringPort):
    def __init__(self) -> None:
        self.events: list[str] = []
        self.started: list[tuple[str, str]] = []

    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        self.started.append((operation_name, operation_type))
        return RecordingMonitoringSpan(self.events)


def test_escalate_alert_to_analyst_calls_aric_and_reports_span() -> None:
    aric = RecordingAricAlertPort()
    monitoring = RecordingMonitoringPort()
    use_case = EscalateAlertToAnalystUseCase(
        aric_alert_port=aric, monitoring=monitoring
    )

    output = use_case.execute(
        EscalateAlertToAnalystInput(
            alert_id=uuid.uuid4(),
            event_id="evt-1",
            session_id="sess-1",
            reason="mandatory data missing: customer_id",
        )
    )

    assert aric.calls == [("evt-1", "sess-1")]
    assert output.aric_signals.is_rat is True
    assert monitoring.started == [
        ("escalate_alert_to_analyst", "workflow.escalation")
    ]
    assert "dependency:aric" in monitoring.events
    assert "finish:None" in monitoring.events
